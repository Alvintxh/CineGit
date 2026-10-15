import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "cinegit.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            for table in ["repos", "commits", "jobs", "listings", "events"]:
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, table, key, db=None):
        if db is None:
            with self.connect() as connection:
                result = self.get(table, key, connection)
            return result
        row = db.execute(f"SELECT data FROM {table} WHERE id = ?", (key,)).fetchone()
        result = json.loads(row[0]) if row else None
        return result

    def all(self, table):
        with self.connect() as db:
            rows = db.execute(f"SELECT data FROM {table} ORDER BY rowid DESC").fetchall()
        result = [json.loads(row[0]) for row in rows]
        return result

    def put(self, table, key, value, db=None):
        if db is None:
            with self.connect() as connection:
                self.put(table, key, value, connection)
        else:
            db.execute(f"INSERT INTO {table}(id, data) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (key, json.dumps(value, ensure_ascii=False)))

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db
