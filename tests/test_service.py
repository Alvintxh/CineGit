import copy

import pytest

from cinegit.service import DomainError, Service, demo_workflow


@pytest.fixture
def service(tmp_path):
    result = Service(tmp_path)
    return result


@pytest.fixture
def repo(service):
    workflow = demo_workflow()
    for node in workflow["nodes"]:
        node["params"]["duration"] = .5
    result = service.create_repo(workflow)
    return result


def test_draft_conflict_and_branch_drafts(service, repo):
    workflow = copy.deepcopy(repo["drafts"]["main"])
    workflow["title"] = "已保存的草稿"
    view = service.save(repo["id"], workflow, 0)
    with pytest.raises(DomainError, match="工作区已更新"):
        service.save(repo["id"], workflow, 0)
    service.branch(repo["id"], "explore")
    branch = service.repo_view(repo["id"])
    branch["workflow"]["title"] = "分支草稿"
    service.save(repo["id"], branch["workflow"], branch["revision"])
    original = service.checkout(repo["id"], "main")
    assert original["workflow"]["title"] == "已保存的草稿"
    assert service.checkout(repo["id"], "explore")["workflow"]["title"] == "分支草稿"
    assert view["dirty"]


def test_distill_preserves_effective_prompts(service, repo):
    before = service.repo_view(repo["id"])
    phrase = "35mm film grain"
    result = service.distill(repo["id"], {"film_style": phrase}, 0)
    assert result["replacements"]["film_style"] == 1
    assert result["workflow"]["variables"]["film_style"] == phrase
    assert [node["node_hash"] for node in before["plan"]] == [node["node_hash"] for node in result["plan"]]


def test_commit_revert_diff_and_fork(service, repo):
    first_job = service.start_commit(repo["id"], "initial", 0, background=False)
    assert first_job["state"] == "success", first_job["error"]
    first = first_job["commit_hash"]
    view = service.branch(repo["id"], "warm")
    workflow = copy.deepcopy(view["workflow"])
    workflow["nodes"][1]["prompt_template"] += "，暖色日落"
    view = service.save(repo["id"], workflow, view["revision"])
    second_job = service.start_commit(repo["id"], "warm", view["revision"], background=False)
    assert second_job["state"] == "success"
    assert second_job["stats"]["cache_hits"] == 2
    assert second_job["stats"]["rendered_nodes"] == 1
    second = second_job["commit_hash"]
    comparison = service.diff(repo["id"], first, second)
    assert comparison["changed_count"] == 1
    assert comparison["changes"][1]["status"] == "modified"
    view = service.checkout(repo["id"], "main")
    picked = service.cherry_pick(repo["id"], second, ["shot_02"], view["revision"])
    assert "暖色日落" in picked["workflow"]["nodes"][1]["prompt_template"]
    third_job = service.start_commit(repo["id"], "picked", picked["revision"], background=False)
    assert third_job["stats"]["cache_hit_rate"] == 100
    view = service.repo_view(repo["id"])
    reverted = service.start_commit(repo["id"], "revert", view["revision"], restore=first, background=False)
    commit = service.require("commits", reverted["commit_hash"])
    assert commit["parent_commit"] == third_job["commit_hash"]
    assert commit["workflow"] == service.require("commits", first)["workflow"]
    assert reverted["stats"]["cache_hit_rate"] == 100
    listing = service.publish(repo["id"], {"title": "模板", "description": "可复用", "price": 10, "tags": []})
    with pytest.raises(DomainError) as error:
        service.fork(listing["id"])
    assert error.value.status_code == 402
    fork = service.fork(listing["id"], True)
    assert fork["forked_from"]["commit_hash"] == reverted["commit_hash"]
    assert all(node["cache_hit"] for node in fork["plan"])
    assert fork["workflow"]["license"] == "CC-BY-4.0"
    receipt = next(event for event in fork["events"] if event["action"] == "market.demo_purchase")
    assert receipt["details"]["platform_fee"] == 1.5
    assert receipt["details"]["real_payment"] is False
    assert service.require("listings", listing["id"])["forks"] == 1


def test_recovery_exposes_interrupted_job(service, repo):
    service.store.put("jobs", "interrupted", {"id": "interrupted", "state": "running", "repo_id": repo["id"]})
    service.recover()
    assert service.require("jobs", "interrupted")["state"] == "error"


def test_cherry_pick_includes_upstream_closure(service, repo):
    workflow = copy.deepcopy(repo["drafts"]["main"])
    workflow["nodes"][1]["depends_on"] = ["shot_01"]
    service.store.put("commits", "source", {"repo_id": repo["id"], "workflow": workflow})
    view = service.cherry_pick(repo["id"], "source", ["shot_02"], 0)
    assert view["workflow"]["nodes"][1]["depends_on"] == ["shot_01"]
    assert service.store.all("events")[0]["details"]["node_ids"] == ["shot_01", "shot_02"]


def test_concurrent_branch_advancement_keeps_conflict_commit(service, repo, monkeypatch):
    original_concat = service.engine.concatenate

    def advance(nodes, output_id):
        output = original_concat(nodes, output_id)
        with service.store.transaction() as db:
            updated = service.require("repos", repo["id"], db)
            updated["branches"]["main"] = "another-head"
            service.store.put("repos", repo["id"], updated, db)
        return output

    monkeypatch.setattr(service.engine, "concatenate", advance)
    job = service.start_commit(repo["id"], "concurrent", 0, background=False)
    assert job["state"] == "conflict"
    assert service.require("commits", job["commit_hash"])["message"] == "concurrent"
    assert service.require("repos", repo["id"])["branches"]["main"] == "another-head"


def test_recovery_does_not_interrupt_another_live_process(service, repo):
    import os
    service.store.put("jobs", "live", {"id": "live", "state": "running", "owner_pid": os.getpid(), "repo_id": repo["id"]})
    service.recover()
    assert service.require("jobs", "live")["state"] == "running"
