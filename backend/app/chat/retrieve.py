"""Gather the evidence for one chat turn in Python, before calling Gemini.

The model gets a single evidence package and answers in one request (no tool loop), so a
turn costs one round trip. The package has:
  1. a drawing index (all 30 drawings)          - organisation / clean-vs-degraded questions
  2. a BOM index (all rows, *active* values)    - shared materials, suppliers, families
  3. focus evidence for the parts the question  - full facts with sources and history,
     matches, plus their linked drawings/rows     extracted drawing text, link scores
  4. recent corrections                          - audit / before-after questions
Everything comes from the knowledge store, so accepted corrections are reflected.
"""
import re

from .. import knowledge as kb

FOCUS_MIN_SCORE = 70     # fuzzy match score needed for a part to get full evidence
MAX_FOCUS_DOCS = 3
MAX_FOCUS_ROWS = 5
DRAWING_TEXT_CHARS = 1200


def _drawing_index(con) -> str:
    lines = ["id | title | subsystem | quality | text layer | 3D reconstruction"]
    for d in kb.list_documents(con):
        lines.append(f"{d['id']} | {d['title']} | {d['subsystem']} | "
                     f"{'DEGRADED scan' if d['distribution'] == 'degraded-only' else 'clean'} | "
                     f"{'yes' if d['has_text_layer'] else 'no'} | {'yes' if d['has_model'] else 'no'}")
    return "\n".join(lines)


def _bom_index(con) -> str:
    rows = con.execute(
        """SELECT b.row_index, b.name,
                  MAX(CASE WHEN f.predicate='part_family' THEN f.value END) AS family,
                  MAX(CASE WHEN f.predicate='type' THEN f.value END) AS type,
                  MAX(CASE WHEN f.predicate='material' THEN f.value END) AS material,
                  MAX(CASE WHEN f.predicate='supplier' THEN f.value END) AS supplier,
                  MAX(CASE WHEN f.predicate='vv_state' THEN f.value END) AS vv,
                  MAX(f.source_type = 'correction') AS corrected
           FROM bom_rows b
           LEFT JOIN facts f ON f.subject_type='bom_row' AND f.subject_id = CAST(b.row_index AS TEXT)
                             AND f.status='active'
           GROUP BY b.row_index ORDER BY b.row_index""").fetchall()
    lines = ["row | name | family | type | material | supplier | V&V   (blank = not recorded; * = has accepted correction)"]
    for r in rows:
        cells = [r["name"], r["family"], r["type"], r["material"], r["supplier"], r["vv"]]
        lines.append(f"{r['row_index']}{'*' if r['corrected'] else ''} | " + " | ".join(c or "" for c in cells))
    return "\n".join(lines)


def _facts_block(facts: list[dict]) -> str:
    out = []
    for f in facts:
        line = f"  - {f['predicate']}: {f['value']}  [{f['source_ref']}]"
        if f["status"] == "superseded":
            line += f"  (SUPERSEDED by fact {f['superseded_by']}; original evidence kept)"
        out.append(line)
    return "\n".join(out) or "  (none)"


def _doc_focus(con, doc_id: str) -> str:
    d = kb.get_document(con, doc_id)
    parts = [f"### Drawing {d['id']} - {d['title']} ({d['subsystem']}, {d['role']})",
             f"quality: {'DEGRADED scan-like derivative' if d['distribution'] == 'degraded-only' else 'clean upstream PDF'}"
             f"; 3D reconstruction: {'yes' if d['model'] else 'no'}; upstream path: {d['source_path']}"]
    if d["derivation"]:
        parts.append(f"degradation notice: {d['derivation'].get('modification_notice')}")
    links = d["bom_links"]
    parts.append("candidate BOM rows (filename fuzzy match, not confirmed): " + (
        "; ".join(f"row {l['row_index']} {l['name']} (score {round(l['score'])})" for l in links) or "none found"))
    parts.append("facts extracted from the drawing:\n" + _facts_block(d["facts"]))
    for p in d["pages_text"]:
        if p["has_text_layer"] and p["text"]:
            txt = re.sub(r"\s+", " ", p["text"])[:DRAWING_TEXT_CHARS]
            parts.append(f"extracted text layer, page {p['page']} (raw, unordered): {txt}")
        else:
            parts.append(f"page {p['page']}: no text layer (raster scan); contents not machine-read yet")
    return "\n".join(parts)


def _row_focus(con, row_index: int) -> str:
    r = kb.get_bom_row(con, row_index)
    parts = [f"### BOM row {row_index} - {r['name']}",
             "facts (active and superseded, with sources):\n" + _facts_block(r["facts"])]
    if r["drawings"]:
        parts.append("candidate drawings: " + "; ".join(
            f"{d['document_id']} {d['title']} (score {round(d['score'])})" for d in r["drawings"]))
    return "\n".join(parts)


def _corrections(con) -> str:
    cs = kb.list_corrections(con)[:15]
    if not cs:
        return "(none yet)"
    return "\n".join(
        f"correction {c['id']} [{c['status']}] {c['subject_type']} {c['subject_id']} {c['predicate']}: "
        f"{c['old_value'] or '(none)'} -> {c['new_value']} (proposed {c['created_at']}"
        f"{', reviewed ' + c['reviewed_at'] if c['reviewed_at'] else ''})" for c in cs)


def focus_targets(con, messages: list[dict]) -> tuple[list[str], list[int], list[dict]]:
    """Which drawings and BOM rows the question is about. Falls back to the previous user
    message for follow-ups like 'and who supplies it?'."""
    user_msgs = [m["content"] for m in messages if m["role"] == "user" and m.get("content")]
    docs: list[str] = []
    rows: list[int] = []
    hits: list[dict] = []
    for text in reversed(user_msgs[-2:]):
        docs += [m.upper() for m in re.findall(r"\bD-\d{3}\b", text, re.I)]
        rows += [int(n) for n in re.findall(r"\brow\s*#?\s*(\d{1,3})\b", text, re.I)]
        found = [h for h in kb.find(con, text, limit=8) if h["score"] >= FOCUS_MIN_SCORE]
        hits += found
        if docs or rows or found:
            break  # the latest message names something; don't drag in the older one
    for h in hits:
        (docs if h["kind"] == "drawing" else rows).append(h["id"] if h["kind"] == "drawing" else h["row_index"])
    docs, rows = list(dict.fromkeys(docs))[:MAX_FOCUS_DOCS], list(dict.fromkeys(rows))
    # Pull in strongly linked counterparts so drawing<->BOM questions have both sides.
    for doc_id in docs:
        rows += [l["row_index"] for l in kb.get_document(con, doc_id)["bom_links"] if l["score"] >= 85]
    rows = list(dict.fromkeys(rows))[:MAX_FOCUS_ROWS]
    return docs, rows, hits


def build_evidence(con, messages: list[dict]) -> tuple[str, list[str], list[int], list[dict]]:
    docs, rows, hits = focus_targets(con, messages)
    focus = [_doc_focus(con, d) for d in docs] + [_row_focus(con, r) for r in rows]
    package = "\n\n".join([
        "## DRAWING INDEX\n" + _drawing_index(con),
        "## BOM INDEX (pinned snapshot; active values incl. accepted corrections)\n" + _bom_index(con),
        "## FOCUS EVIDENCE (parts matched to the question)\n" + ("\n\n".join(focus) or "(no specific part matched)"),
        "## CORRECTIONS\n" + _corrections(con),
    ])
    return package, docs, rows, hits
