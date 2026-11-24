"""Ingest a new drawing uploaded through the app.

Pipeline (runs in the background after the upload request returns):
  1. save the PDF to data/uploads/U-0nn.pdf and record it in data/uploads/manifest.json
  2. register it as a document (subsystem chosen by the uploader)
  3. PDF text layer -> data/extracted/U-0nn.json
  4. vision pass (title block, dimensions, callouts, with checks) if an API key is set
  5. propose a drawing -> BOM link as a *pending correction* (proposed_via 'ingest') so a human
     reviews it in the Review page, with the usual verification checks
Uploads, their extraction output and any accepted link survive rebuilds (manifest + journal).
"""
import hashlib
import json
import threading
from datetime import datetime, timezone

import pymupdf

from . import config, consistency, metrics
from . import knowledge as kb
from .config import DATA, EXTRACTED, ROOT
from .db import connect

UPLOAD_DIR = DATA / "uploads"
MANIFEST = UPLOAD_DIR / "manifest.json"
_lock = threading.Lock()
STATUS: dict[str, dict] = {}  # in-memory progress for the UI


def _load() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []


def _save(items: list[dict]) -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(items, indent=1), encoding="utf-8")


def save_upload(data: bytes, filename: str, subsystem: str) -> dict:
    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
        pages = len(pdf)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"not a readable PDF: {e}")
    sha = hashlib.sha256(data).hexdigest()
    with _lock:
        items = _load()
        dup = next((u for u in items if u["sha256"] == sha), None)
        if dup:
            raise ValueError(f"this file was already uploaded as {dup['id']}")
        n = max([int(u["id"][2:]) for u in items] + [0]) + 1
        uid = f"U-{n:03d}"
        path = UPLOAD_DIR / f"{uid}.pdf"
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
        item = {"id": uid, "path": rel, "subsystem": subsystem.strip() or "Unassigned",
                "original_filename": filename, "sha256": sha, "pages": pages,
                "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _save(items + [item])
    STATUS[uid] = {"id": uid, "state": "queued", "steps": []}
    return item


def process(uid: str) -> None:
    """Background pipeline; progress is visible at GET /api/uploads/{uid}."""
    from .ingest import drawings, manifest, vision

    st = STATUS.setdefault(uid, {"id": uid, "steps": []})

    def step(msg):
        st["steps"].append(msg)
        st["state"] = "processing"

    con = connect()
    try:
        manifest.load_uploads(con)
        con.commit()
        doc = dict(con.execute("SELECT * FROM documents WHERE id=?", (uid,)).fetchone())
        step("registered drawing")
        data = drawings.extract_text_layer(doc)
        (EXTRACTED / f"{uid}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        for p in data["pages"]:
            con.execute("INSERT OR REPLACE INTO drawing_pages (document_id, page, width, height, has_text_layer, text) VALUES (?,?,?,?,?,?)",
                        (uid, p["page"], p["width"], p["height"], int(p["has_text_layer"]), p["text"]))
        con.commit()
        step(f"text layer: {'found' if not data['needs_vision'] else 'none (raster scan)'}")
        if config.GEMINI_API_KEY:
            out = vision.extract({**doc, "distribution": "degraded-only" if data["needs_vision"] else "clean"})
            (vision.VISION_DIR / f"{uid}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
            con.execute("DELETE FROM facts WHERE subject_type='document' AND subject_id=? AND source_type='drawing'", (uid,))
            con.execute("DELETE FROM drawing_annotations WHERE document_id=?", (uid,))
            drawings.load_vision(con, uid)
            con.commit()
            step(f"vision pass: {len(out['pages'][0]['dimensions'])} dimensions, {len(out['pages'][0]['callouts'])} callouts")
        else:
            step("vision pass skipped (no API key)")
        proposal = _propose_link(con, uid)
        step(proposal)
        consistency.run(con)
        con.commit()
        metrics.record(con, f"drawing {uid} ingested")
        st["state"] = "done"
    except Exception as e:  # noqa: BLE001
        st["state"] = "failed"
        st["steps"].append(f"failed: {type(e).__name__}: {e}")
    finally:
        con.close()


def _propose_link(con, uid: str) -> str:
    title = con.execute("""SELECT value FROM facts WHERE subject_type='document' AND subject_id=? AND predicate='title'
                           AND status='active' AND value IS NOT NULL""", (uid,)).fetchone()
    filename_title = con.execute("SELECT title FROM documents WHERE id=?", (uid,)).fetchone()["title"]
    names = [x for x in (title["value"] if title else "", filename_title) if x]
    names += [t for t in map(kb._translate, names) if t]  # Danish titles -> English BOM names
    query = " ".join(dict.fromkeys(names))
    hits = [h for h in kb.find(con, query, limit=5) if h["kind"] == "bom_row"]
    if not hits or hits[0]["score"] < 80:
        return f"no BOM row matched {query!r} well enough to propose a link (best: " + (
            f"row {hits[0]['row_index']} {hits[0]['name']} {hits[0]['score']})" if hits else "none)")
    h = hits[0]
    c = kb.propose_correction(con, "document", uid, "bom_link", str(h["row_index"]),
                              f"Proposed at ingest: sheet/file title {query!r} matches BOM row {h['row_index']} "
                              f"{h['name']!r} (score {h['score']}).", "ingest")
    if c.get("duplicate"):
        return f"link to BOM row {h['row_index']} ({h['name']}) is already pending as correction #{c['id']}"
    return f"proposed link to BOM row {h['row_index']} ({h['name']}) as correction #{c['id']} for review"


def start(uid: str) -> None:
    threading.Thread(target=process, args=(uid,), daemon=True, name=f"ingest-{uid}").start()


def status(uid: str) -> dict | None:
    if uid in STATUS:
        return STATUS[uid]
    if any(u["id"] == uid for u in _load()):
        return {"id": uid, "state": "done", "steps": ["processed earlier"]}
    return None
