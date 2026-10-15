import time

from fastapi.testclient import TestClient

from cinegit import api as api_module
from cinegit.service import Service, demo_workflow


def test_http_studio_workflow(tmp_path, monkeypatch):
    service = Service(tmp_path)
    monkeypatch.setattr(api_module, "service", service)
    monkeypatch.setenv("CINEGIT_SEED_DEMO", "false")
    with TestClient(api_module.app) as client:
        assert client.get("/api/health").json()["status"] == "success"
        assert client.post("/api/import", json={"nodes": []}).status_code == 422
        workflow = demo_workflow()
        workflow["nodes"] = workflow["nodes"][:1]
        workflow["nodes"][0]["params"]["duration"] = .5
        response = client.post("/api/repos", json=workflow)
        assert response.status_code == 200
        repo = response.json()["repo"]
        repo_id = repo["id"]
        assert client.get(f"/api/repos/{repo_id}").json()["repo"]["workflow"] == repo["workflow"]
        assert client.get("/api/repos/nonexistent").status_code == 404
        assert client.post(f"/api/repos/{repo_id}/preview/shot_01").status_code == 200
        exported = client.get(f"/api/repos/{repo_id}/export")
        assert exported.json()["schema_version"] == "1.0"
        imported = client.post("/api/import", json=exported.json())
        assert imported.status_code == 200
        assert imported.json()["repo"]["id"] != repo_id
        draft = client.put(f"/api/repos/{repo_id}/draft", json={"workflow": workflow, "revision": 0})
        assert draft.status_code == 200
        assert client.put(f"/api/repos/{repo_id}/draft", json={"workflow": workflow, "revision": 0}).status_code == 409
        revision = draft.json()["repo"]["revision"]
        job = client.post(f"/api/repos/{repo_id}/commits", json={"message": "HTTP integration", "revision": revision}).json()["job"]
        for attempt in range(100):
            job = client.get(f"/api/jobs/{job['id']}").json()["job"]
            if job["state"] in {"success", "error"}:
                break
            time.sleep(.05)
        assert job["state"] == "success", job
        data = client.post(f"/api/repos/{repo_id}/publish", json={"title": "模板", "description": "描述", "price": 0}).json()
        listing_id = data["listing"]["id"]
        assert client.get("/api/market").json()["real_payment"] is False
        fork = client.post(f"/api/market/{listing_id}/fork", json={"accept_demo_purchase": False})
        assert fork.status_code == 200
        assert fork.json()["repo"]["forked_from"]["commit_hash"] == job["commit_hash"]
        assert client.post("/api/repos", json=None).status_code == 200
