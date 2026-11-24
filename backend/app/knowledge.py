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

from . import consistency
from .ingest import interfaces

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
        """SELECT l.row_index, l.score, l.method, l.status, l.rationale, b.name, b.part_family, b.material
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
    doc["link_decision"] = one_row(con.execute(
        "SELECT status, rationale FROM link_decisions WHERE document_id = ?", (doc_id,)))
    doc["consistency"] = consistency.for_document(con, doc_id)
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
        """SELECT l.document_id, l.score, l.method, l.status, l.rationale, d.title
           FROM doc_bom_links l JOIN documents d ON d.id = l.document_id
           WHERE l.row_index = ? AND l.status != 'rejected' ORDER BY l.score DESC""", (row_index,)))
    row["consistency"] = consistency.for_row(con, row_index)
    row.update(interfaces.for_row(con, row_index))
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


# Danish words common in this corpus's drawing names -> English, so "build base ring" finds "Bygge Base Ring".
DA_EN = {"bygge": "build", "plade": "plate", "spænd": "clamp", "spaend": "clamp", "varmeelement": "heating element",
         "varme": "heating", "element": "element", "bund": "bottom", "bundplade": "bottom plate", "montage": "mount",
         "klods": "block", "pakning": "gasket", "silikone": "silicone", "cylinder": "cylinder"}


def _translate(name: str) -> str:
    words = re.sub(r"(?<=[a-zæøå])(?=[A-Z])", " ", name).split()
    out = [DA_EN.get(w.lower(), w) for w in words]
    t = " ".join(out)
    return t if t.lower() != name.lower() else ""


def _norm_words(s: str) -> str:
    return " " + re.sub(r"[^a-z0-9æøå]+", " ", s.lower()).strip() + " "


def find(con, query: str, limit: int = 8) -> list[dict]:
    """Fuzzy match a free-text part reference against drawing titles and BOM names.
    An explicit drawing id (e.g. 'D-012') in the query is an exact hit, and a part whose full name
    appears verbatim in the query scores 100 (long questions otherwise dilute fuzzy scores)."""
    cands: dict[str, tuple[str, dict]] = {}
    names: dict[str, list[str]] = {}  # every name a candidate is known by, for verbatim matching
    # Match drawings on the file name, the title read from the title block, and English translations
    # (file names are often Danish, e.g. "ByggePlade" vs title "Build Plate").
    sheet_titles = {r["subject_id"]: r["value"] for r in con.execute(
        "SELECT subject_id, value FROM facts WHERE subject_type='document' AND predicate='title' "
        "AND status='active' AND value IS NOT NULL")}
    for d in con.execute("SELECT id, title, subsystem, distribution FROM documents"):
        variants = [d["title"]] + ([sheet_titles[d["id"]]] if d["id"] in sheet_titles else [])
        variants += [t for t in map(_translate, variants) if t]
        cands[f"doc:{d['id']}"] = (" ".join(dict.fromkeys(variants)), {"kind": "drawing", **dict(d)})
        names[f"doc:{d['id']}"] = variants
    for b in con.execute("SELECT row_index, name, part_family, type FROM bom_rows WHERE name IS NOT NULL"):
        cands[f"bom:{b['row_index']}"] = (b["name"], {"kind": "bom_row", **dict(b)})
        names[f"bom:{b['row_index']}"] = [b["name"]]
    hits = process.extract(query, {k: v[0] for k, v in cands.items()}, scorer=_part_score,
                           processor=lambda s: s.lower(), limit=limit)
    scores = {key: round(score, 1) for _, score, key in hits}
    q = _norm_words(query)
    for key, variants in names.items():
        for v in variants:
            nv = _norm_words(re.sub(r"(?<=[a-zæøå])(?=[A-Z])", " ", v))
            if len(nv.strip()) >= 5 and nv in q:
                # longer verbatim names rank above shorter ones they contain ("silicone gun" > "silicone")
                scores[key] = max(scores.get(key, 0), 100.0 + min(len(nv), 40) / 10)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
    out = [{**cands[key][1], "score": min(score, 100.0), "_rank": score} for key, score in ranked]
    for doc_id in dict.fromkeys(m.upper() for m in re.findall(r"\bD-\d{3}\b", query, re.I)):
        if f"doc:{doc_id}" in cands:
            out = [h for h in out if h.get("id") != doc_id]
            out.insert(0, {**cands[f"doc:{doc_id}"][1], "score": 100.0, "_rank": 200.0})
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
    report: dict = {"checks": [], "current_facts": []}

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

    if predicate == "bom_link":  # drawing <-> BOM link correction (see links.py)
        from . import links
        if subject_type != "document":
            add("subject type", False, "link corrections are made on a drawing (subject_type 'document')")
            return report
        report.update(links.check(con, subject_id, new_value, add))
        return report

    current = all_rows(con.execute(
        "SELECT id, value, source_type, source_ref FROM facts WHERE subject_type=? AND subject_id=? AND predicate=? AND status='active'",
        (subject_type, subject_id, predicate)))
    report["current_facts"] = current
    add("changes something", all(f["value"] != new_value for f in current),
        "new value differs from all active values" if current else "no active value; this adds one")
    sources = {f["source_type"] for f in current}
    add("independent sources", len(sources) <= 1,
        f"active values come from {sorted(sources)}" if sources else "no prior evidence")
    report["drawing_evidence"] = _drawing_evidence(con, subject_type, subject_id, predicate, new_value, add)
    return report


def _drawing_evidence(con, subject_type, subject_id, predicate, new_value, add) -> list[dict]:
    """Cross-check a proposed BOM value against what the linked drawing(s) say.
    The check informs the reviewer; a mismatch does not block acceptance."""
    from . import consistency

    if subject_type != "bom_row" or predicate not in ("material", "amount"):
        return []
    links = all_rows(con.execute(
        """SELECT document_id, status FROM doc_bom_links
           WHERE row_index = ? AND method IN ('curated','correction') AND status IN ('confirmed','probable')""", (subject_id,)))
    if not links:
        add("drawing evidence", True, "no reviewed drawing is linked to this BOM row; nothing to compare")
        return []
    out = []
    for l in links:
        doc = l["document_id"]
        if predicate == "material":
            dval, dref = consistency.drawing_material(con, doc)
            if not dval:
                add("drawing evidence", True, f"{doc} ({l['status']} link) states no material")
                continue
            d, n = consistency.material_classes(dval), consistency.material_classes(new_value)
            ok = bool(d & n) or not n
            add("drawing evidence", ok, f"{doc} ({l['status']} link) says {dval!r} [{dref}] -> "
                + ("consistent with the proposed value" if ok else "CONTRADICTS the proposed value"))
            out.append({"document_id": doc, "drawing_value": dval, "drawing_ref": dref, "consistent": ok})
        else:
            title = con.execute("SELECT title FROM documents WHERE id=?", (doc,)).fetchone()["title"]
            note = con.execute("""SELECT value FROM facts WHERE subject_type='document' AND subject_id=?
                                  AND predicate='note' AND status='active'""", (doc,)).fetchone()
            qty = consistency.drawing_quantity(title, note["value"] if note else "")
            if not qty or not str(new_value).strip().isdigit():
                add("drawing evidence", True, f"{doc} states no quantity to compare")
                continue
            ok = qty[0] <= int(new_value) <= qty[1]
            add("drawing evidence", ok, f"{doc} states {qty[0]}{'' if qty[0] == qty[1] else '-' + str(qty[1])} pieces -> "
                + ("consistent" if ok else "CONTRADICTS the proposed value"))
            out.append({"document_id": doc, "drawing_value": qty, "consistent": ok})
    return out


def propose_correction(con, subject_type, subject_id, predicate, new_value, rationale="",
                       proposed_via="chat", journal=True, at: str | None = None) -> dict:
    subject_id = str(subject_id)
    if journal:  # live proposals only; replay must reproduce the journal (and its ids) exactly
        dup = _pending_duplicate(con, subject_type, subject_id, predicate, new_value)
        if dup:
            return {**get_correction(con, dup), "duplicate": True}
    report = _check(con, subject_type, subject_id, predicate, new_value)
    old = "; ".join(f"{f['value']} ({f['source_ref']})" for f in report["current_facts"]) or None
    cur = con.execute(
        """INSERT INTO corrections (created_at, proposed_via, subject_type, subject_id, predicate, old_value, new_value,
                                   rationale, check_report)
           VALUES (COALESCE(?, datetime('now')),?,?,?,?,?,?,?,?)""",
        (at, proposed_via, subject_type, subject_id, predicate, old, new_value, rationale, json.dumps(report)))
    cid = cur.lastrowid
    audit(con, "proposed", "correction", cid, {"predicate": predicate, "new_value": new_value}, at=at)
    con.commit()
    if journal:
        _journal({"event": "proposed", "subject_type": subject_type, "subject_id": subject_id, "predicate": predicate,
                  "new_value": new_value, "rationale": rationale, "proposed_via": proposed_via})
    return get_correction(con, cid)


def _same_value(predicate: str, a: str, b: str) -> bool:
    if predicate == "bom_link":  # "91,93" == "93, 91"
        from . import links
        ra, rb = links.parse_rows(a), links.parse_rows(b)
        if ra is not None and rb is not None:
            return sorted(ra) == sorted(rb)
    return (a or "").strip().lower() == (b or "").strip().lower()


def _pending_duplicate(con, subject_type, subject_id, predicate, new_value) -> int | None:
    """Id of a pending correction that already proposes this exact change, if any."""
    for r in con.execute("""SELECT id, new_value FROM corrections WHERE status='pending'
                            AND subject_type=? AND subject_id=? AND predicate=? ORDER BY id""",
                         (subject_type, subject_id, predicate)):
        if _same_value(predicate, r["new_value"], new_value):
            return r["id"]
    return None


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


def review_correction(con, cid: int, accept: bool, note: str = "", journal=True, at: str | None = None) -> dict:
    c = get_correction(con, cid)
    if not c:
        raise KeyError(cid)
    if c["status"] != "pending":
        raise ValueError(f"correction {cid} is already {c['status']}")
    new_fact_id = None
    if accept and c["predicate"] == "bom_link":
        from . import links
        links.apply(con, c["subject_id"], c["new_value"], cid)
    elif accept:
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
        "UPDATE corrections SET status=?, reviewed_at=COALESCE(?, datetime('now')), reviewer_note=?, new_fact_id=? WHERE id=?",
        ("accepted" if accept else "rejected", at, note, new_fact_id, cid))
    audit(con, "accepted" if accept else "rejected", "correction", cid, {"note": note, "new_fact_id": new_fact_id}, at=at)
    if accept:
        from . import consistency
        consistency.run(con)  # drawing-vs-BOM checks now see the corrected value
    con.commit()
    if journal:
        _journal({"event": "accepted" if accept else "rejected", "id": cid, "note": note})
        from . import metrics
        metrics.record(con, f"correction {cid} {'accepted' if accept else 'rejected'} ({c['predicate']})")
    return get_correction(con, cid)


def _sql_ts(iso: str | None) -> str | None:
    """Journal ISO timestamp -> SQLite 'YYYY-MM-DD HH:MM:SS' (UTC), so replays keep original times."""
    return iso[:19].replace("T", " ") if iso else None


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
                               e.get("rationale", ""), e.get("proposed_via", "chat"), journal=False, at=_sql_ts(e.get("ts")))
        elif e["event"] in ("accepted", "rejected"):
            review_correction(con, e["id"], e["event"] == "accepted", e.get("note", ""), journal=False,
                              at=_sql_ts(e.get("ts")))
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
