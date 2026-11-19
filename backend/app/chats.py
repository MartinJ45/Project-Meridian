"""Chat history, stored in data/chats.db.

Kept apart from meridian.db because ingest deletes and rebuilds that file; chats must
survive a knowledge rebuild. Each assistant message keeps its metadata (attachments,
trace, latency) so a reopened chat can still open its drawings and 3D views.
"""
import json
import uuid

from .config import CHATS_DB_PATH
from .db import all_rows, connect, one_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,              -- user | assistant
    content     TEXT NOT NULL,
    meta        TEXT,                       -- JSON for assistant turns
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages(chat_id, id);
"""

TITLE_CHARS = 60


def open_db():
    con = connect(CHATS_DB_PATH)
    con.executescript(SCHEMA)
    return con


def _title(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= TITLE_CHARS else text[:TITLE_CHARS - 1].rstrip() + "…"


def create_chat(con, first_message: str) -> dict:
    cid = uuid.uuid4().hex[:12]
    con.execute("INSERT INTO chats (id, title) VALUES (?, ?)", (cid, _title(first_message)))
    con.commit()
    return {"id": cid, "title": _title(first_message)}


def list_chats(con) -> list[dict]:
    return all_rows(con.execute(
        """SELECT c.id, c.title, c.created_at, c.updated_at,
                  (SELECT COUNT(*) FROM chat_messages m WHERE m.chat_id = c.id) AS message_count
           FROM chats c ORDER BY c.updated_at DESC, c.created_at DESC"""))


def get_chat(con, cid: str) -> dict | None:
    chat = one_row(con.execute("SELECT * FROM chats WHERE id = ?", (cid,)))
    if not chat:
        return None
    msgs = all_rows(con.execute(
        "SELECT role, content, meta, created_at FROM chat_messages WHERE chat_id = ? ORDER BY id", (cid,)))
    for m in msgs:
        m["meta"] = json.loads(m["meta"]) if m["meta"] else None
    chat["messages"] = msgs
    return chat


def history(con, cid: str) -> list[dict]:
    """Messages in the shape the chat agent expects."""
    return [{"role": r["role"], "content": r["content"]} for r in con.execute(
        "SELECT role, content FROM chat_messages WHERE chat_id = ? ORDER BY id", (cid,))]


def add_message(con, cid: str, role: str, content: str, meta: dict | None = None) -> None:
    con.execute("INSERT INTO chat_messages (chat_id, role, content, meta) VALUES (?,?,?,?)",
                (cid, role, content, json.dumps(meta) if meta else None))
    con.execute("UPDATE chats SET updated_at = datetime('now') WHERE id = ?", (cid,))
    con.commit()


def delete_chat(con, cid: str) -> bool:
    con.execute("DELETE FROM chat_messages WHERE chat_id = ?", (cid,))
    deleted = con.execute("DELETE FROM chats WHERE id = ?", (cid,)).rowcount
    con.commit()
    return bool(deleted)
