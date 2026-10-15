import copy
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone

from .engine import Engine, digest
from .models import Node, Workflow
from .store import Store


def now():
    result = datetime.now(timezone.utc).isoformat()
    return result


def identifier():
    result = uuid.uuid4().hex
    return result


def process_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class DomainError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class Service:
    def __init__(self, root):
        self.store = Store(root)
        self.engine = Engine(root)
        self.threads = set()
        self.threads_lock = threading.Lock()

    def recover(self):
        for job in self.store.all("jobs"):
            if job["state"] in {"queued", "running"} and not process_alive(job.get("owner_pid")):
                job.update(state="error", error="服务上次退出时任务中断，请重新提交；已生成节点仍保留在缓存中。")
                self.store.put("jobs", job["id"], job)

    def require(self, table, key, db=None):
        result = self.store.get(table, key, db)
        if result is None:
            raise DomainError("资源不存在", 404)
        return result

    def event(self, repo_id, action, details, db=None):
        event_id = identifier()
        self.store.put("events", event_id, {"id": event_id, "repo_id": repo_id, "action": action, "details": details, "created_at": now()}, db)

    def create_repo(self, workflow, forked_from=None):
        workflow = Workflow.model_validate(workflow).model_dump()
        repo_id = identifier()
        repo = {"id": repo_id, "title": workflow["title"], "created_at": now(), "branches": {"main": None}, "current_branch": "main", "drafts": {"main": workflow}, "revision": 0, "forked_from": forked_from}
        self.store.put("repos", repo_id, repo)
        self.event(repo_id, "repository.created", {"forked_from": forked_from})
        return repo

    def repo_view(self, repo_id):
        repo = self.require("repos", repo_id)
        head = repo["branches"][repo["current_branch"]]
        workflow = repo["drafts"][repo["current_branch"]]
        commit = self.require("commits", head) if head else None
        planned = self.engine.plan(workflow)
        return {**repo, "workflow": workflow, "head": head, "commit": commit, "plan": planned, "dirty": commit is None or commit["workflow"] != workflow, "jobs": [job for job in self.store.all("jobs") if job["repo_id"] == repo_id][:10], "commits": [item for item in self.store.all("commits") if item["repo_id"] == repo_id], "events": [event for event in self.store.all("events") if event["repo_id"] == repo_id][:40]}

    def mutate(self, repo_id, revision, transform):
        with self.store.transaction() as db:
            repo = self.require("repos", repo_id, db)
            if revision != repo["revision"]:
                raise DomainError("工作区已更新，请刷新后重试", 409)
            workflow = copy.deepcopy(repo["drafts"][repo["current_branch"]])
            transformed = transform(workflow)
            validated = Workflow.model_validate(transformed).model_dump()
            repo["drafts"][repo["current_branch"]] = validated
            repo["title"] = validated["title"]
            repo["revision"] += 1
            self.store.put("repos", repo_id, repo, db)
        result = self.repo_view(repo_id)
        return result

    def save(self, repo_id, workflow, revision):
        result = self.mutate(repo_id, revision, lambda existing: workflow)
        return result

    def record(self, repo_id, node, revision):
        node = Node.model_validate(node).model_dump()

        def append(workflow):
            if any(item["node_id"] == node["node_id"] for item in workflow["nodes"]):
                raise DomainError("节点 ID 已存在")
            workflow["nodes"].append(node)
            return workflow

        result = self.mutate(repo_id, revision, append)
        self.event(repo_id, "mcp.tool.recorded", {"tool": node["mcp_tool"], "node_id": node["node_id"], "params": node["params"]})
        return result

    def distill(self, repo_id, variables, revision):
        if any(not value for value in variables.values()):
            raise DomainError("蒸馏原文不能为空")
        replacements = {key: 0 for key in variables}

        def transform(workflow):
            for name, value in sorted(variables.items(), key=lambda pair: len(pair[1]), reverse=True):
                for node in workflow["nodes"]:
                    count = node["prompt_template"].count(value)
                    replacements[name] += count
                    node["prompt_template"] = node["prompt_template"].replace(value, "{{" + name + "}}")
                workflow["variables"][name] = value
            return workflow

        result = self.mutate(repo_id, revision, transform)
        self.event(repo_id, "workflow.parameterized", {"replacements": replacements, "method": "literal"})
        return {**result, "replacements": replacements}

    def branch(self, repo_id, name, from_commit=None):
        with self.store.transaction() as db:
            repo = self.require("repos", repo_id, db)
            if name in repo["branches"]:
                raise DomainError("分支已存在", 409)
            head = from_commit or repo["branches"][repo["current_branch"]]
            if head:
                commit = self.require("commits", head, db)
                if commit["repo_id"] != repo_id:
                    raise DomainError("提交不属于此仓库")
                workflow = commit["workflow"]
            else:
                workflow = repo["drafts"][repo["current_branch"]]
            repo["branches"][name] = head
            repo["drafts"][name] = workflow
            repo["current_branch"] = name
            repo["revision"] += 1
            self.store.put("repos", repo_id, repo, db)
            self.event(repo_id, "branch.created", {"name": name, "from_commit": head}, db)
        result = self.repo_view(repo_id)
        return result

    def checkout(self, repo_id, name):
        with self.store.transaction() as db:
            repo = self.require("repos", repo_id, db)
            if name not in repo["branches"]:
                raise DomainError("分支不存在", 404)
            repo["current_branch"] = name
            repo["revision"] += 1
            self.store.put("repos", repo_id, repo, db)
        result = self.repo_view(repo_id)
        return result

    def cherry_pick(self, repo_id, commit_id, node_ids, revision):
        commit = self.require("commits", commit_id)
        if commit["repo_id"] != repo_id:
            raise DomainError("提交不属于此仓库")
        source = {node["node_id"]: node for node in commit["workflow"]["nodes"]}
        if not set(node_ids) <= source.keys():
            raise DomainError("选择中包含不存在的节点")
        required = set(node_ids)
        queue = list(node_ids)
        while queue:
            node_id = queue.pop()
            for dep in source[node_id]["depends_on"]:
                if dep not in required:
                    required.add(dep)
                    queue.append(dep)

        def transform(workflow):
            current = {node["node_id"]: node for node in workflow["nodes"]}
            for node in commit["workflow"]["nodes"]:
                if node["node_id"] in required:
                    current[node["node_id"]] = node
                    for name in re.findall(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}", node["prompt_template"]):
                        workflow["variables"][name] = commit["workflow"]["variables"][name]
            workflow["nodes"] = list(current.values())
            return workflow

        result = self.mutate(repo_id, revision, transform)
        self.event(repo_id, "nodes.cherry_picked", {"commit": commit_id, "node_ids": sorted(required)})
        return result

    def start_commit(self, repo_id, message, revision, restore=None, background=True):
        with self.store.transaction() as db:
            repo = self.require("repos", repo_id, db)
            if revision != repo["revision"]:
                raise DomainError("工作区已更新，请刷新后重试", 409)
            branch = repo["current_branch"]
            workflow = repo["drafts"][branch]
            if restore:
                old = self.require("commits", restore, db)
                if old["repo_id"] != repo_id:
                    raise DomainError("提交不属于此仓库")
                workflow = old["workflow"]
            job_id = identifier()
            job = {"id": job_id, "repo_id": repo_id, "branch": branch, "expected_head": repo["branches"][branch], "revision": revision, "workflow": workflow, "message": message, "state": "queued", "owner_pid": os.getpid(), "progress": 0, "total": len(workflow["nodes"]), "created_at": now(), "nodes": [], "error": None, "restore": restore}
            self.store.put("jobs", job_id, job, db)
        if background:
            thread = threading.Thread(target=self.run_job, args=(job_id,), daemon=True)
            with self.threads_lock:
                self.threads.add(thread)
            thread.start()
        else:
            self.run_job(job_id)
        result = self.require("jobs", job_id)
        return result

    def run_job(self, job_id):
        job = self.require("jobs", job_id)
        started = time.perf_counter()
        try:
            job["state"] = "running"
            self.store.put("jobs", job_id, job)
            planned = self.engine.plan(job["workflow"])
            rendered = {}
            for node in planned:
                output = self.engine.render_node(node, rendered)
                rendered[node["node_id"]] = output
                job["nodes"].append(output)
                job["progress"] += 1
                self.store.put("jobs", job_id, job)
            nodes = [rendered[node["node_id"]] for node in job["workflow"]["nodes"]]
            output = self.engine.concatenate(nodes, job_id)
            hits = sum(node["cache_hit"] for node in nodes)
            video_nodes = [node for node in nodes if node["mcp_tool"] == "mcp_video_gen"]
            saved_estimate = sum(node["cache_hit"] for node in video_nodes) * float(os.getenv("CINEGIT_ESTIMATED_SHOT_COST", "0.25"))
            stats = {"cache_hits": hits, "total_nodes": len(nodes), "cache_hit_rate": round(hits / len(nodes) * 100, 1), "rendered_nodes": len(nodes) - hits, "elapsed_ms": round((time.perf_counter() - started) * 1000), "estimated_saved_usd": saved_estimate, "fallback_nodes": sum(bool(node.get("fallback")) for node in nodes), **output}
            commit = {"repo_id": job["repo_id"], "parent_commit": job["expected_head"], "branch": job["branch"], "message": job["message"], "created_at": now(), "workflow": job["workflow"], "nodes": nodes, "stats": stats, "reverts": job["restore"], "provider": self.engine.provider}
            commit_hash = digest(commit)
            commit["hash"] = commit_hash
            with self.store.transaction() as db:
                repo = self.require("repos", job["repo_id"], db)
                self.store.put("commits", commit_hash, commit, db)
                if repo["branches"][job["branch"]] != job["expected_head"]:
                    job.update(state="conflict", error="分支已前移。渲染结果已保留，可从该提交创建分支。", commit_hash=commit_hash, stats=stats)
                else:
                    repo["branches"][job["branch"]] = commit_hash
                    if repo["drafts"][job["branch"]] == job["workflow"] or (job["restore"] and repo["revision"] == job["revision"]):
                        repo["drafts"][job["branch"]] = job["workflow"]
                    repo["revision"] += 1
                    self.store.put("repos", repo["id"], repo, db)
                    job.update(state="success", commit_hash=commit_hash, stats=stats, finished_at=now())
                self.store.put("jobs", job_id, job, db)
                self.event(job["repo_id"], "commit." + job["state"], {"commit": commit_hash, "stats": stats}, db)
        except Exception as error:
            job.update(state="error", error=str(error), finished_at=now())
            self.store.put("jobs", job_id, job)
        finally:
            with self.threads_lock:
                self.threads.discard(threading.current_thread())

    def diff(self, repo_id, left_id, right_id):
        repo = self.require("repos", repo_id)
        left = self.require("commits", left_id)
        if left["repo_id"] != repo_id:
            raise DomainError("提交不属于此仓库")
        if right_id == "working":
            right = {"workflow": repo["drafts"][repo["current_branch"]], "message": "工作区", "hash": "working", "stats": {}}
        else:
            right = self.require("commits", right_id)
            if right["repo_id"] != repo_id:
                raise DomainError("提交不属于此仓库")
        left_plan = {node["node_id"]: node for node in self.engine.plan(left["workflow"])}
        right_plan = {node["node_id"]: node for node in self.engine.plan(right["workflow"])}
        changes = []
        for node_id in dict.fromkeys([*left_plan, *right_plan]):
            before, after = left_plan.get(node_id), right_plan.get(node_id)
            status = "added" if not before else "removed" if not after else "unchanged" if before["node_hash"] == after["node_hash"] else "modified"
            fields = []
            if before and after:
                for field in ["prompt_template", "resolved_prompt", "params", "depends_on", "mcp_tool"]:
                    if before[field] != after[field]:
                        fields.append({"field": field, "before": before[field], "after": after[field]})
            changes.append({"node_id": node_id, "title": (after or before)["title"], "status": status, "before": before, "after": after, "fields": fields})
        return {"left": left, "right": right, "changes": changes, "changed_count": sum(change["status"] != "unchanged" for change in changes)}

    def publish(self, repo_id, data):
        repo = self.require("repos", repo_id)
        head = repo["branches"][repo["current_branch"]]
        if not head:
            raise DomainError("请先完成一次 Commit")
        commit = self.require("commits", head)
        listing_id = identifier()
        listing = {"id": listing_id, "repo_id": repo_id, "commit_hash": head, "author": commit["workflow"]["author"], "license": commit["workflow"]["license"], "created_at": now(), "forks": 0, "preview_img": next((node["preview_img"] for node in commit["nodes"] if node.get("preview_img")), None), "video_url": commit["stats"]["video_url"], "node_count": len(commit["nodes"]), "duration": commit["stats"]["duration"], **data}
        self.store.put("listings", listing_id, listing)
        self.event(repo_id, "workflow.published", {"listing_id": listing_id})
        return listing

    def fork(self, listing_id, accept_demo_purchase=False):
        with self.store.transaction() as db:
            listing = self.require("listings", listing_id, db)
            if listing["price"] > 0 and not accept_demo_purchase:
                raise DomainError("此模板需要确认演示购买；本平台当前不处理真实付款", 402)
            commit = self.require("commits", listing["commit_hash"], db)
            listing["forks"] += 1
            self.store.put("listings", listing_id, listing, db)
        workflow = copy.deepcopy(commit["workflow"])
        workflow["title"] += " / Fork"
        repo = self.create_repo(workflow, {"listing_id": listing_id, "repo_id": listing["repo_id"], "commit_hash": listing["commit_hash"], "license": listing["license"]})
        if listing["price"] > 0:
            self.event(repo["id"], "market.demo_purchase", {"amount": listing["price"], "platform_fee": round(listing["price"] * 0.15, 2), "currency": "USD", "real_payment": False})
        result = self.repo_view(repo["id"])
        return result


def demo_workflow():
    return {"title": "雨夜来信", "description": "一座失眠的城市，一封来自未来的信。三幕赛博电影短片。", "author": "@cinegit_studio", "license": "CC-BY-4.0", "variables": {"protagonist": "撑透明雨伞的机甲少女", "environment": "暴雨中的未来霓虹都市"}, "nodes": [
        {"node_id": "shot_01", "title": "城市醒来之前", "mcp_tool": "mcp_video_gen", "prompt_template": "电影级远景，{{environment}}，高耸建筑间雾气流动，青绿色霓虹倒映在积水中，35mm film grain", "params": {"seed": 884210, "camera_motion": "pan_right", "duration": 3}, "depends_on": []},
        {"node_id": "shot_02", "title": "一个未接来电", "mcp_tool": "mcp_video_gen", "prompt_template": "中景，{{protagonist}}独自站在{{environment}}的街口，风衣轻轻摆动，镜头缓缓推近，cinematic lighting", "params": {"seed": 102938, "camera_motion": "zoom_in", "duration": 3}, "depends_on": []},
        {"node_id": "shot_03", "title": "向光而行", "mcp_tool": "mcp_video_gen", "prompt_template": "远景，{{protagonist}}走向{{environment}}的天际线，雨幕渐渐消散，月光穿过云层，anamorphic widescreen", "params": {"seed": 731902, "camera_motion": "zoom_out", "duration": 3}, "depends_on": []},
    ]}


def seed_demo(service):
    if service.store.all("repos"):
        return
    repo = service.create_repo(demo_workflow())
    initial = service.start_commit(repo["id"], "开场：雨夜来信 · 三幕分镜", 0, background=False)
    if initial["state"] != "success":
        raise RuntimeError(initial["error"])
    service.branch(repo["id"], "explore/amber")
    view = service.repo_view(repo["id"])
    workflow = copy.deepcopy(view["workflow"])
    workflow["nodes"][1]["prompt_template"] += "，日落暖色调，琥珀色光晕"
    view = service.save(repo["id"], workflow, view["revision"])
    service.start_commit(repo["id"], "探索：让第二幕进入琥珀色黄昏", view["revision"], background=False)
    service.checkout(repo["id"], "main")
    service.branch(repo["id"], "explore/closeup")
    view = service.repo_view(repo["id"])
    workflow = copy.deepcopy(view["workflow"])
    workflow["nodes"][1]["params"]["camera_motion"] = "pan_left"
    workflow["nodes"][1]["params"]["seed"] = 202610
    view = service.save(repo["id"], workflow, view["revision"])
    service.start_commit(repo["id"], "探索：街角的另一种视线", view["revision"], background=False)
    service.checkout(repo["id"], "main")
    service.publish(repo["id"], {"title": "雨夜来信 · 赛博电影三部曲", "description": "可复用的三幕电影配方。替换主角与场景，开始你的故事。", "price": 0, "tags": ["电影感", "赛博朋克", "三幕结构"]})
    service.checkout(repo["id"], "explore/amber")
    service.publish(repo["id"], {"title": "琥珀时刻 · 暖调城市叙事", "description": "冷暖交织的城市片段，包含可调节的运镜与确定性种子。", "price": 9, "tags": ["暖调", "城市", "运镜"]})
    service.checkout(repo["id"], "main")
