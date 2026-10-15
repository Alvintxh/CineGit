import json
import os
from pathlib import Path

from dotenv import load_dotenv

from cinegit.service import Service, seed_demo

load_dotenv()
root = Path(os.getenv("CINEGIT_DATA_DIR", ".data"))
service = Service(root)
seed_demo(service)
for repo in service.store.all("repos"):
    view = service.repo_view(repo["id"])
    print(json.dumps({"repo_id": repo["id"], "title": view["workflow"]["title"], "branches": repo["branches"], "video_url": view["commit"]["stats"]["video_url"] if view["commit"] else None}, ensure_ascii=False, indent=2))
