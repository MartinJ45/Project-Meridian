"""Read/write access to the extracted knowledge. Shared by the HTTP API and the chat tools.

Correction lifecycle (the governed loop):
  propose  -> a `corrections` row with a check report; nothing in `facts` changes
  accept   -> the targeted active facts are marked superseded (not deleted) and a new
              fact with source_type='correction' becomes active
  reject   -> the correction is closed; facts untouched
Every event is also appended to data/corrections.jsonl, which ingest replays after a
rebuild, so reviewed knowledge survives re-extraction.
"""
import json
import re
from datetime import datetime, timezone

from rapidfuzz import fuzz, process

from .config import DATA, MODELS_DIR, ROOT
from .db import all_rows, audit, one_row

JOURNAL = DATA / "corrections.jsonl"
SUBJECT_TYPES = ("bom_row", "document")

RECONSTRUCTION_LABEL = "Reconstruction from 2D drawing evidence - not native CAD"


# ---------------------------------------------------------------- lookups

def list_documents(con) -> list[dict]:
    docs = all_rows(con.execute(
        """SELECT d.id, d.title, d.subsystem, d.distribution, d.role, d.pages,
                  (SELECT MAX(has_text_layer) FROM drawing_pages p WHERE p.document_id = d.id) AS has_text_layer,
                  EXISTS(SELECT 1 FROM models3d m WHERE m.document_id = d.id) AS has_model
           FROM documents d ORDER BY d.id"""))
    for d in docs:
        d["has_model"] = bool(d["has_model"])
    return docs


def get_document(con, doc_id: str) -> dict | None:
    doc = one_row(con.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)))
    if not doc:
        return None
    doc["derivation"] = json.loads(doc["derivation"]) if doc["derivation"] else None
    doc["pages_text"] = all_rows(con.execute(
        "SELECT page, has_text_layer, text FROM drawing_pages WHERE document_id = ? ORDER BY page", (doc_id,)))
    doc["bom_links"] = all_rows(con.execute(
        """SELECT l.row_index, l.score, l.method, l.status, b.name, b.part_family, b.material
           FROM doc_bom_links l JOIN bom_rows b USING(row_index)
           WHERE l.document_id = ? AND l.status != 'rejected' ORDER BY l.score DESC""", (doc_id,)))
    doc["facts"] = facts_for(con, "document", doc_id)
    doc["quality"] = all_rows(con.execute(
        "SELECT page, legibility, issues, extractor FROM drawing_quality WHERE document_id = ? ORDER BY page", (doc_id,)))
    doc["annotations"] = all_rows(con.execute(
        "SELECT page, kind, feature, text, legibility, box_2d FROM drawing_annotations WHERE document_id = ? ORDER BY kind DESC, id",
        (doc_id,)))
    for a in doc["annotations"]:
        a["box_2d"] = json.loads(a["box_2d"]) if a["box_2d"] else None
    doc["model"] = get_model(con, doc_id)
    doc["file_url"] = f"/api/documents/{doc_id}/file"
    return doc


def get_model(con, doc_id: str) -> dict | None:
    m = one_row(con.execute("SELECT * FROM models3d WHERE document_id = ?", (doc_id,)))
    if not m:
        return None
    return {
        "document_id": doc_id,
        "url": f"/files/models/{doc_id}.glb",
        "method": m["method"],
        "spec": json.loads(m["spec_json"]),
        "label": RECONSTRUCTION_LABEL,
    }


def get_bom_row(con, row_index: int) -> dict | None:
    row = one_row(con.execute("SELECT * FROM bom_rows WHERE row_index = ?", (row_index,)))
    if not row:
        return None
    row["raw"] = json.loads(row.pop("raw_json"))
    row["facts"] = facts_for(con, "bom_row", str(row_index))
    row["drawings"] = all_rows(con.execute(
        """SELECT l.document_id, l.score, l.method, l.status, d.title
           FROM doc_bom_links l JOIN documents d ON d.id = l.document_id
           WHERE l.row_index = ? AND l.status != 'rejected' ORDER BY l.score DESC""", (row_index,)))
    return row


def search_bom(con, q: str = "", limit: int = 50) -> list[dict]:
    if not q:
        return all_rows(con.execute(
            "SELECT row_index, name, part_family, type, material, supplier FROM bom_rows ORDER BY row_index LIMIT ?", (limit,)))
    like = f"%{q}%"
    return all_rows(con.execute(
        """SELECT row_index, name, part_family, type, material, supplier FROM bom_rows
           WHERE name LIKE ? OR material LIKE ? OR supplier LIKE ? OR part_family LIKE ? OR interface_with LIKE ?
           ORDER BY row_index LIMIT ?""", (like, like, like, like, like, limit)))


def facts_for(con, subject_type: str, subject_id: str, include_superseded: bool = True) -> list[dict]:
    sql = "SELECT * FROM facts WHERE subject_type = ? AND subject_id = ?"
    if not include_superseded:
        sql += " AND status = 'active'"
    rows = all_rows(con.execute(sql + " ORDER BY predicate, id", (subject_type, str(subject_id))))
    for r in rows:
        r["evidence"] = json.loads(r["evidence"]) if r.get("evidence") else None
    return rows


def _part_score(query: str, choice: str, **kwargs) -> float:
    # token_set tolerates extra words in a question ("show me the X"); WRatio breaks ties.
    return 0.7 * fuzz.token_set_ratio(query, choice, **kwargs) + 0.3 * fuzz.WRatio(query, choice, **kwargs)


def find(con, query: str, limit: int = 8) -> list[dict]:
    """Fuzzy match a free-text part reference against drawing titles and BOM names.
    An explicit drawing id (e.g. 'D-012') in the query is an exact hit."""
    cands: dict[str, tuple[str, dict]] = {}
    # Match drawings on the file name and on the title read from the title block
    # (file names are often Danish, e.g. "ByggePlade" vs title "Build Plate").
    sheet_titles = {r["subject_id"]: r["value"] for r in con.execute(
        "SELECT subject_id, value FROM facts WHERE subject_type='document' AND predicate='title' "
        "AND status='active' AND value IS NOT NULL")}
    for d in con.execute("SELECT id, title, subsystem, distribution FROM documents"):
        name = d["title"] + (f" {sheet_titles[d['id']]}" if d["id"] in sheet_titles else "")
        cands[f"doc:{d['id']}"] = (name, {"kind": "drawing", **dict(d)})
    for b in con.execute("SELECT row_index, name, part_family, type FROM bom_rows WHERE name IS NOT NULL"):
        cands[f"bom:{b['row_index']}"] = (b["name"], {"kind": "bom_row", **dict(b)})
    hits = process.extract(query, {k: v[0] for k, v in cands.items()}, scorer=_part_score,
                           processor=lambda s: s.lower(), limit=limit)
    out = [{**cands[key][1], "score": round(score, 1)} for _, score, key in hits]
    for doc_id in dict.fromkeys(m.upper() for m in re.findall(r"\bD-\d{3}\b", query, re.I)):
        if f"doc:{doc_id}" in cands:
            out = [h for h in out if h.get("id") != doc_id]
            out.insert(0, {**cands[f"doc:{doc_id}"][1], "score": 100.0})
    return out[:limit]


def search_drawing_text(con, q: str, limit: int = 10) -> list[dict]:
    return all_rows(con.execute(
        """SELECT document_id, page, substr(text, max(1, instr(lower(text), lower(?)) - 80), 200) AS snippet
           FROM drawing_pages WHERE text LIKE ? LIMIT ?""", (q, f"%{q}%", limit)))


# ---------------------------------------------------------------- corrections

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _journal(event: dict) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _now(), **event}, ensure_ascii=False) + "\n")


def _check(con, subject_type: str, subject_id: str, predicate: str, new_value: str) -> dict:
    """Automated checks shown to the reviewer. They inform the human; they do not decide."""
    report: dict = {"checks": []}

    def add(name, ok, detail):
        report["checks"].append({"name": name, "ok": ok, "detail": detail})

    if subject_type == "bom_row":
        exists = con.execute("SELECT name FROM bom_rows WHERE row_index = ?", (subject_id,)).fetchone()
        add("subject exists", bool(exists), f"BOM row {subject_id}: {exists['name']}" if exists else "no such BOM row")
    elif subject_type == "document":
        exists = con.execute("SELECT title FROM documents WHERE id = ?", (subject_id,)).fetchone()
        add("subject exists", bool(exists), f"{subject_id}: {exists['title']}" if exists else "no such drawing")
    else:
        add("subject type", False, f"unknown subject type {subject_type!r}")

    current = all_rows(con.execute(
        "SELECT id, value, source_type, source_ref FROM facts WHERE subject_type=? AND subject_id=? AND predicate=? AND status='active'",
        (subject_type, subject_id, predicate)))
    report["current_facts"] = current
    add("changes something", all(f["value"] != new_value for f in current),
        "new value differs from all active values" if current else "no active value; this adds one")
    sources = {f["source_type"] for f in current}
    add("independent sources", len(sources) <= 1,
        f"active values come from {sorted(sources)}" if sources else "no prior evidence")
    # TODO: cross-check against drawing extraction (e.g. material in title block) when available
    return report


def propose_correction(con, subject_type, subject_id, predicate, new_value, rationale="",
                       proposed_via="chat", journal=True) -> dict:
    subject_id = str(subject_id)
    report = _check(con, subject_type, subject_id, predicate, new_value)
    old = "; ".join(f"{f['value']} ({f['source_ref']})" for f in report["current_facts"]) or None
    cur = con.execute(
        """INSERT INTO corrections (proposed_via, subject_type, subject_id, predicate, old_value, new_value, rationale, check_report)
           VALUES (?,?,?,?,?,?,?,?)""",
        (proposed_via, subject_type, subject_id, predicate, old, new_value, rationale, json.dumps(report)))
    cid = cur.lastrowid
    audit(con, "proposed", "correction", cid, {"predicate": predicate, "new_value": new_value})
    con.commit()
    if journal:
        _journal({"event": "proposed", "subject_type": subject_type, "subject_id": subject_id, "predicate": predicate,
                  "new_value": new_value, "rationale": rationale, "proposed_via": proposed_via})
    return get_correction(con, cid)


def get_correction(con, cid: int) -> dict | None:
    c = one_row(con.execute("SELECT * FROM corrections WHERE id = ?", (cid,)))
    if c:
        c["check_report"] = json.loads(c["check_report"] or "{}")
    return c


def list_corrections(con, status: str | None = None) -> list[dict]:
    sql, args = "SELECT id FROM corrections", ()
    if status:
        sql, args = sql + " WHERE status = ?", (status,)
    return [get_correction(con, r["id"]) for r in con.execute(sql + " ORDER BY id DESC", args)]


def review_correction(con, cid: int, accept: bool, note: str = "", journal=True) -> dict:
    c = get_correction(con, cid)
    if not c:
        raise KeyError(cid)
    if c["status"] != "pending":
        raise ValueError(f"correction {cid} is already {c['status']}")
    new_fact_id = None
    if accept:
        cur = con.execute(
            """INSERT INTO facts (subject_type, subject_id, predicate, value, source_type, source_ref, confidence)
               VALUES (?,?,?,?, 'correction', ?, 1.0)""",
            (c["subject_type"], c["subject_id"], c["predicate"], c["new_value"], f"correction {cid}"))
        new_fact_id = cur.lastrowid
        con.execute(
            """UPDATE facts SET status='superseded', superseded_by=?
               WHERE subject_type=? AND subject_id=? AND predicate=? AND status='active' AND id != ?""",
            (new_fact_id, c["subject_type"], c["subject_id"], c["predicate"], new_fact_id))
    con.execute(
        "UPDATE corrections SET status=?, reviewed_at=datetime('now'), reviewer_note=?, new_fact_id=? WHERE id=?",
        ("accepted" if accept else "rejected", note, new_fact_id, cid))
    audit(con, "accepted" if accept else "rejected", "correction", cid, {"note": note, "new_fact_id": new_fact_id})
    con.commit()
    if journal:
        _journal({"event": "accepted" if accept else "rejected", "id": cid, "note": note})
    return get_correction(con, cid)


def replay_corrections(con) -> int:
    """Re-apply the journal after a rebuild. IDs are reproduced because replay order is preserved."""
    if not JOURNAL.exists():
        return 0
    n = 0
    for line in JOURNAL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e["event"] == "proposed":
            propose_correction(con, e["subject_type"], e["subject_id"], e["predicate"], e["new_value"],
                               e.get("rationale", ""), e.get("proposed_via", "chat"), journal=False)
        elif e["event"] in ("accepted", "rejected"):
            review_correction(con, e["id"], e["event"] == "accepted", e.get("note", ""), journal=False)
        n += 1
    return n


def audit_log(con, limit: int = 200) -> list[dict]:
    rows = all_rows(con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)))
    for r in rows:
        r["detail"] = json.loads(r["detail"] or "{}")
    return rows


def stats(con) -> dict:
    q = lambda sql: con.execute(sql).fetchone()[0]
    return {
        "documents": q("SELECT COUNT(*) FROM documents"),
        "bom_rows": q("SELECT COUNT(*) FROM bom_rows"),
        "facts_active": q("SELECT COUNT(*) FROM facts WHERE status='active'"),
        "doc_bom_links": q("SELECT COUNT(*) FROM doc_bom_links"),
        "models3d": q("SELECT COUNT(*) FROM models3d"),
        "corrections_pending": q("SELECT COUNT(*) FROM corrections WHERE status='pending'"),
    }
