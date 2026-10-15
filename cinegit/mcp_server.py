import json
import os
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from .service import Service, demo_workflow

load_dotenv()
root = Path(__file__).resolve().parent.parent
service = Service(Path(os.getenv("CINEGIT_DATA_DIR", str(root / ".data"))))
service.recover()
mcp = FastMCP("CineGit", instructions="Record and replay creative workflows. Route generation through cinegit_generate to automatically record prompts, seeds, parameters and upstream assets.", host="127.0.0.1", port=int(os.getenv("CINEGIT_MCP_PORT", "8001")))


def tool_result(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            result = function(*args, **kwargs)
            return result
        except Exception as error:
            data = {"status": "error", "message": str(error)}
            result = CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))], structuredContent=data)
            return result
    return wrapped


@mcp.tool()
@tool_result
def cinegit_list_repositories():
    """List local creative repositories and their branches."""
    return {"status": "success", "repos": service.store.all("repos")}


@mcp.tool()
@tool_result
def cinegit_create_repository(title: str = "新影片"):
    """Create a video workflow repository with a starter storyboard."""
    workflow = demo_workflow()
    workflow["title"] = title
    repo = service.create_repo(workflow)
    return {"status": "success", "repo_id": repo["id"], "revision": repo["revision"]}


@mcp.tool()
@tool_result
def cinegit_get_workflow(repo_id: str):
    """Read workflow, revision, DAG hashes, branch history and cached outputs."""
    repo = service.repo_view(repo_id)
    return {"status": "success", "repo": repo}


@mcp.tool()
@tool_result
def cinegit_generate(repo_id: str, node_id: str, prompt: str, tool: str = "mcp_video_gen", seed: int = 42, duration: float = 3, camera_motion: str = "zoom_in", depends_on: list[str] | None = None):
    """Generate an asset through the gateway and automatically record the tool call and dependencies. Supports video, image, script and demo tone/remote TTS."""
    view = service.repo_view(repo_id)
    node = {"node_id": node_id, "title": node_id, "mcp_tool": tool, "prompt_template": prompt, "params": {"seed": seed, "duration": duration, "camera_motion": camera_motion}, "depends_on": depends_on or []}
    existing = next((item for item in view["workflow"]["nodes"] if item["node_id"] == node_id), None)
    if existing:
        workflow = view["workflow"]
        workflow["nodes"] = [node if item["node_id"] == node_id else item for item in workflow["nodes"]]
        view = service.save(repo_id, workflow, view["revision"])
        service.event(repo_id, "mcp.tool.recorded", {"node_id": node_id, "tool": tool, "params": node["params"]})
    else:
        view = service.record(repo_id, node, view["revision"])
    needed = {node_id}
    by_id = {item["node_id"]: item for item in view["plan"]}
    queue = [node_id]
    while queue:
        current = queue.pop()
        for dep in by_id[current]["depends_on"]:
            if dep not in needed:
                needed.add(dep)
                queue.append(dep)
    artifacts = {}
    for item in view["plan"]:
        if item["node_id"] in needed:
            artifacts[item["node_id"]] = service.engine.render_node(item, artifacts)
    service.event(repo_id, "mcp.tool.completed", {"node_id": node_id, "artifact": artifacts[node_id]["artifact"], "node_hash": artifacts[node_id]["node_hash"]})
    return {"status": "success", "node": artifacts[node_id], "revision": view["revision"]}


@mcp.tool()
@tool_result
def cinegit_parameterize(repo_id: str, variables: dict[str, str]):
    """Replace supplied literal phrases with reusable {{variable}} slots across all nodes."""
    view = service.repo_view(repo_id)
    repo = service.distill(repo_id, variables, view["revision"])
    return {"status": "success", "workflow": repo["workflow"], "replacements": repo["replacements"]}


@mcp.tool()
@tool_result
def cinegit_commit(repo_id: str, message: str):
    """Render cache misses, concatenate the film and create a commit asynchronously; poll cinegit_job."""
    view = service.repo_view(repo_id)
    job = service.start_commit(repo_id, message, view["revision"])
    return {"status": "success", "job": job}


@mcp.tool()
@tool_result
def cinegit_job(job_id: str):
    """Read render job progress, failure details, actual timings and cache statistics."""
    job = service.require("jobs", job_id)
    return {"status": "success", "job": job}


@mcp.tool()
@tool_result
def cinegit_branch(repo_id: str, name: str, from_commit: str | None = None):
    """Create and check out an exploration branch from a commit."""
    from .models import BranchRequest
    validated = BranchRequest(name=name, from_commit=from_commit)
    repo = service.branch(repo_id, validated.name, validated.from_commit)
    return {"status": "success", "repo": repo}


@mcp.tool()
@tool_result
def cinegit_checkout(repo_id: str, branch: str):
    """Switch branches; each branch keeps its own draft."""
    repo = service.checkout(repo_id, branch)
    return {"status": "success", "repo": repo}


@mcp.tool()
@tool_result
def cinegit_diff(repo_id: str, left_commit: str, right_commit: str = "working"):
    """Compare rendered prompts, parameters and dependency hashes between versions."""
    diff = service.diff(repo_id, left_commit, right_commit)
    return {"status": "success", **diff}


@mcp.tool()
@tool_result
def cinegit_revert(repo_id: str, commit_hash: str):
    """Restore an old snapshot as a new commit, preserving history."""
    view = service.repo_view(repo_id)
    job = service.start_commit(repo_id, "Revert to " + commit_hash[:8], view["revision"], restore=commit_hash)
    return {"status": "success", "job": job}


@mcp.tool()
@tool_result
def cinegit_cherry_pick(repo_id: str, commit_hash: str, node_ids: list[str]):
    """Copy selected shots, their dependency closure and referenced variables into the draft."""
    view = service.repo_view(repo_id)
    repo = service.cherry_pick(repo_id, commit_hash, node_ids, view["revision"])
    return {"status": "success", "workflow": repo["workflow"], "revision": repo["revision"]}


@mcp.tool()
@tool_result
def cinegit_marketplace():
    """Browse published workflow templates pinned to immutable commits."""
    return {"status": "success", "listings": service.store.all("listings"), "real_payment": False}


@mcp.tool()
@tool_result
def cinegit_fork(listing_id: str, accept_demo_purchase: bool = False):
    """Fork a marketplace workflow. Paid listings use explicitly confirmed demo purchases only."""
    repo = service.fork(listing_id, accept_demo_purchase)
    return {"status": "success", "repo": repo}


@mcp.resource("cinegit://repositories/{repo_id}/workflow")
def workflow_resource(repo_id: str):
    view = service.repo_view(repo_id)
    result = json.dumps(view["workflow"], ensure_ascii=False, indent=2)
    return result


if __name__ == "__main__":
    mcp.run(transport=os.getenv("CINEGIT_MCP_TRANSPORT", "stdio"))
