import asyncio
import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .models import BranchRequest, CherryPickRequest, CommitRequest, DistillRequest, PublishRequest, RecordRequest, SaveDraft, Workflow
from .service import DomainError, Service, demo_workflow, seed_demo

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("CINEGIT_DATA_DIR", str(ROOT / ".data"))).resolve()
service = Service(DATA)


@asynccontextmanager
async def lifespan(app):
    service.recover()
    if os.getenv("CINEGIT_SEED_DEMO", "true").lower() == "true" and not service.store.all("repos"):
        if not shutil.which("ffmpeg"):
            raise RuntimeError("请安装 FFmpeg 后启动 CineGit")
        await asyncio.to_thread(seed_demo, service)
    yield
    threads = list(service.threads)
    for thread in threads:
        await asyncio.to_thread(thread.join, 10)


app = FastAPI(title="CineGit", version="0.1.0", lifespan=lifespan)
app.mount("/media/cache", StaticFiles(directory=service.engine.cache), name="cache")
app.mount("/media/outputs", StaticFiles(directory=service.engine.outputs), name="outputs")


@app.exception_handler(DomainError)
async def domain_error(request: Request, error: DomainError):
    response = JSONResponse(status_code=error.status_code, content={"status": "error", "message": str(error)})
    return response


@app.exception_handler(ValidationError)
async def validation_error(request: Request, error: ValidationError):
    response = JSONResponse(status_code=422, content={"status": "error", "message": str(error)})
    return response


@app.exception_handler(RequestValidationError)
async def request_validation_error(request: Request, error: RequestValidationError):
    message = "；".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors())
    response = JSONResponse(status_code=422, content={"status": "error", "message": message})
    return response


@app.exception_handler(RuntimeError)
async def runtime_error(request: Request, error: RuntimeError):
    response = JSONResponse(status_code=502, content={"status": "error", "message": str(error)})
    return response


@app.get("/api/health")
def health():
    return {"status": "success", "provider": "http" if service.engine.endpoint else "demo", "ffmpeg": bool(shutil.which("ffmpeg")), "real_payment": False}


@app.get("/api/repos")
def list_repos():
    repos = [{key: repo[key] for key in ["id", "title", "created_at", "current_branch", "forked_from"]} for repo in service.store.all("repos")]
    return {"status": "success", "repos": repos}


@app.post("/api/repos")
def create_repo(workflow: Workflow | None = None):
    repo = service.create_repo(workflow.model_dump() if workflow else demo_workflow())
    result = service.repo_view(repo["id"])
    return {"status": "success", "repo": result}


@app.get("/api/repos/{repo_id}")
def get_repo(repo_id: str):
    result = service.repo_view(repo_id)
    return {"status": "success", "repo": result}


@app.put("/api/repos/{repo_id}/draft")
def save_draft(repo_id: str, data: SaveDraft):
    result = service.save(repo_id, data.workflow.model_dump(), data.revision)
    return {"status": "success", "repo": result}


@app.post("/api/repos/{repo_id}/record")
def record(repo_id: str, data: RecordRequest):
    result = service.record(repo_id, data.node.model_dump(), data.revision)
    return {"status": "success", "repo": result}


@app.get("/api/repos/{repo_id}/distill-suggestions")
def distill_suggestions(repo_id: str):
    repo = service.repo_view(repo_id)
    counts = {}
    for node in repo["workflow"]["nodes"]:
        text = re.sub(r"{{.*?}}", "", node["prompt_template"])
        for phrase in set(re.split(r"[，。；,;\n]", text)):
            phrase = phrase.strip()
            if 4 <= len(phrase) <= 60:
                counts[phrase] = counts.get(phrase, 0) + 1
    suggestions = [{"name": f"variable_{index + 1}", "value": phrase, "occurrences": count} for index, (phrase, count) in enumerate(sorted(counts.items(), key=lambda item: -item[1])) if count >= 2]
    return {"status": "success", "method": "repeated_phrase", "suggestions": suggestions[:10]}


@app.post("/api/repos/{repo_id}/distill")
def distill(repo_id: str, data: DistillRequest):
    result = service.distill(repo_id, data.variables, data.revision)
    return {"status": "success", "repo": result}


@app.post("/api/repos/{repo_id}/preview/{node_id}")
def preview(repo_id: str, node_id: str):
    repo = service.repo_view(repo_id)
    node = next((item for item in repo["plan"] if item["node_id"] == node_id), None)
    if node is None:
        raise DomainError("分镜不存在", 404)
    result = service.engine.preview(node)
    return {"status": "success", **result, "node_hash": node["node_hash"], "provider": "http" if service.engine.endpoint else "demo"}


@app.post("/api/repos/{repo_id}/commits")
def commit(repo_id: str, data: CommitRequest):
    job = service.start_commit(repo_id, data.message, data.revision)
    return {"status": "success", "job": job}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = service.require("jobs", job_id)
    return {"status": "success", "job": job}


@app.post("/api/repos/{repo_id}/branches")
def create_branch(repo_id: str, data: BranchRequest):
    result = service.branch(repo_id, data.name, data.from_commit)
    return {"status": "success", "repo": result}


@app.post("/api/repos/{repo_id}/checkout")
def checkout(repo_id: str, data: BranchRequest):
    result = service.checkout(repo_id, data.name)
    return {"status": "success", "repo": result}


@app.post("/api/repos/{repo_id}/revert/{commit_id}")
def revert(repo_id: str, commit_id: str, data: CommitRequest):
    job = service.start_commit(repo_id, data.message, data.revision, restore=commit_id)
    return {"status": "success", "job": job}


@app.post("/api/repos/{repo_id}/cherry-pick")
def cherry_pick(repo_id: str, data: CherryPickRequest):
    result = service.cherry_pick(repo_id, data.commit, data.node_ids, data.revision)
    return {"status": "success", "repo": result}


@app.get("/api/repos/{repo_id}/diff")
def diff(repo_id: str, left: str, right: str = "working"):
    result = service.diff(repo_id, left, right)
    return {"status": "success", **result}


@app.get("/api/repos/{repo_id}/export")
def export_workflow(repo_id: str):
    view = service.repo_view(repo_id)
    content = {"schema_version": "1.0", "repo_id": repo_id, "commit_hash": None if view["dirty"] else view["head"], "base_commit": view["head"], "parent_commit": view["head"] if view["dirty"] else view["commit"]["parent_commit"] if view["commit"] else None, **view["workflow"]}
    response = Response(json.dumps(content, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="workflow.json"'})
    return response


@app.post("/api/import")
def import_workflow(workflow: Workflow):
    repo = service.create_repo(workflow.model_dump())
    result = service.repo_view(repo["id"])
    return {"status": "success", "repo": result}


@app.get("/api/market")
def market():
    return {"status": "success", "listings": service.store.all("listings"), "real_payment": False, "platform_fee_percent": 15}


@app.post("/api/repos/{repo_id}/publish")
def publish(repo_id: str, data: PublishRequest):
    listing = service.publish(repo_id, data.model_dump())
    return {"status": "success", "listing": listing}


@app.post("/api/market/{listing_id}/fork")
def fork(listing_id: str, accept_demo_purchase: bool = Body(default=False, embed=True)):
    result = service.fork(listing_id, accept_demo_purchase)
    return {"status": "success", "repo": result}


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/")
    def index():
        response = FileResponse(DIST / "index.html")
        return response
