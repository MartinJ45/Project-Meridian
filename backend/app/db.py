import json
import sqlite3
from pathlib import Path

from .config import DB_PATH

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def all_rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def one_row(cur) -> dict | None:
    r = cur.fetchone()
    return dict(r) if r else None


def audit(con: sqlite3.Connection, action: str, entity: str, entity_id, detail: dict | None = None) -> None:
    con.execute(
        "INSERT INTO audit_log(action, entity, entity_id, detail) VALUES (?,?,?,?)",
        (action, entity, str(entity_id) if entity_id is not None else None, json.dumps(detail or {})),
    )
