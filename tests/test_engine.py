import copy
import json
import subprocess

import pytest
from pydantic import ValidationError

from cinegit.engine import Engine, plan_workflow
from cinegit.models import Workflow
from cinegit.service import demo_workflow


def hashes(workflow):
    result = {node["node_id"]: node["node_hash"] for node in plan_workflow(workflow)}
    return result


def test_hash_is_canonical_and_ignores_unused_variables():
    workflow = demo_workflow()
    before = hashes(workflow)
    workflow["variables"]["unused"] = "不会触发渲染"
    workflow["nodes"][0]["params"] = dict(reversed(list(workflow["nodes"][0]["params"].items())))
    workflow["nodes"][0]["title"] = "只改名称"
    assert hashes(workflow) == before


def test_variable_only_invalidates_referencing_nodes():
    workflow = demo_workflow()
    before = hashes(workflow)
    workflow["variables"]["protagonist"] = "一只橘猫"
    after = hashes(workflow)
    assert after["shot_01"] == before["shot_01"]
    assert after["shot_02"] != before["shot_02"]
    assert after["shot_03"] != before["shot_03"]


def test_changes_invalidate_transitive_dependents_only():
    workflow = demo_workflow()
    workflow["nodes"][2]["depends_on"] = ["shot_02"]
    before = hashes(workflow)
    workflow["nodes"][1]["params"]["seed"] += 1
    after = hashes(workflow)
    assert before["shot_01"] == after["shot_01"]
    assert before["shot_02"] != after["shot_02"]
    assert before["shot_03"] != after["shot_03"]


def test_provider_identity_invalidates_cache():
    workflow = demo_workflow()
    assert plan_workflow(workflow, "demo")[0]["node_hash"] != plan_workflow(workflow, "remote")[0]["node_hash"]


def test_topological_order_preserves_film_order():
    workflow = demo_workflow()
    workflow["nodes"][0]["depends_on"] = ["shot_03"]
    planned = plan_workflow(workflow)
    assert next(i for i, node in enumerate(planned) if node["node_id"] == "shot_03") < next(i for i, node in enumerate(planned) if node["node_id"] == "shot_01")
    assert workflow["nodes"][0]["node_id"] == "shot_01"


@pytest.mark.parametrize("invalid", ["cycle", "missing_dependency", "duplicate", "missing_variable", "bad_seed", "bad_duration", "bad_motion", "no_video"])
def test_reject_invalid_workflows(invalid):
    workflow = demo_workflow()
    if invalid == "cycle":
        workflow["nodes"][0]["depends_on"] = ["shot_02"]
        workflow["nodes"][1]["depends_on"] = ["shot_01"]
    elif invalid == "missing_dependency":
        workflow["nodes"][0]["depends_on"] = ["missing"]
    elif invalid == "duplicate":
        workflow["nodes"][1]["node_id"] = "shot_01"
    elif invalid == "missing_variable":
        workflow["variables"].pop("environment")
    elif invalid == "bad_seed":
        workflow["nodes"][0]["params"]["seed"] = -1
    elif invalid == "bad_duration":
        workflow["nodes"][0]["params"]["duration"] = 0
    elif invalid == "bad_motion":
        workflow["nodes"][0]["params"]["camera_motion"] = "invalid"
    else:
        for node in workflow["nodes"]:
            node["mcp_tool"] = "mcp_image_gen"
    with pytest.raises(ValidationError):
        Workflow.model_validate(workflow)


def test_actual_render_cache_normalization_and_concat(tmp_path):
    tmp_path = tmp_path / "creator's project"
    engine = Engine(tmp_path)
    workflow = demo_workflow()
    workflow["nodes"] = workflow["nodes"][:2]
    for node in workflow["nodes"]:
        node["params"]["duration"] = .5
    planned = engine.plan(workflow)
    rendered = [engine.render_node(node, {}) for node in planned]
    assert all(not node["cache_hit"] for node in rendered)
    cached = [engine.render_node(node, {}) for node in planned]
    assert all(node["cache_hit"] and node["elapsed_ms"] == 0 for node in cached)
    concatenated = engine.concatenate(rendered, "test")
    path = tmp_path / concatenated["video_url"].removeprefix("/media/")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    metadata = json.loads(probe.stdout)
    video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in metadata["streams"] if stream["codec_type"] == "audio")
    assert (video["width"], video["height"], video["pix_fmt"], video["r_frame_rate"], video["time_base"]) == (1280, 720, "yuv420p", "24/1", "1/12288")
    assert (audio["channels"], audio["sample_rate"]) == (2, "48000")
    assert abs(float(metadata["format"]["duration"]) - 1) < .1
    decode = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    assert decode.returncode == 0
    assert decode.stderr == ""
    changed = copy.deepcopy(workflow)
    changed["nodes"][1]["params"]["seed"] += 1
    next_plan = engine.plan(changed)
    assert [node["cache_hit"] for node in next_plan] == [True, False]


def test_import_ignores_untrusted_derived_cache_metadata():
    workflow = demo_workflow()
    workflow["repo_id"] = "external_repo"
    workflow["commit_hash"] = "external_commit"
    workflow["nodes"][0].update(node_hash="bogus", artifact_mp4="/arbitrary/file.mp4", preview_img="https://untrusted.example/image.webp")
    validated = Workflow.model_validate(workflow).model_dump()
    assert "node_hash" not in validated["nodes"][0]
    assert "artifact_mp4" not in validated["nodes"][0]
    assert "repo_id" not in validated
    assert len(plan_workflow(validated)[0]["node_hash"]) == 64
