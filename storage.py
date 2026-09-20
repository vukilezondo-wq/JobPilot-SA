"""
Storage layer — single-file JSON store for this MVP.

NOTE for whoever productionizes this: replace with a real database
(Postgres/SQLite) with a row per client before this serves real users.
A flat JSON file is fine for local testing but is NOT multi-tenant and
NOT safe for concurrent users.
"""
from pathlib import Path
from datetime import datetime, timezone
import json

DB_PATH = Path("jobpilot_data.json")

DEFAULT_DATA = {
    "candidate": {},
    "cv_text": "",
    "jobs": [],
    "applications": [],
    "settings": {"plan": "Free", "consent": False},
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load() -> dict:
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text())
    return json.loads(json.dumps(DEFAULT_DATA))  # deep copy, no shared refs


def save(data: dict) -> None:
    DB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))
