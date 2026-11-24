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
import json
import re

from .. import consistency
from .. import knowledge as kb

FOCUS_MIN_SCORE = 70     # fuzzy match score needed for a part to get full evidence
RELATIVE_WINDOW = 10
REVIEWED = ("curated", "correction")  # link methods that count as reviewed     # ...and within this many points of the best match
MAX_FOCUS_DOCS = 3
MAX_FOCUS_ROWS = 5
DRAWING_TEXT_CHARS = 1200


def _drawing_index(con) -> str:
    tb = {}
    for r in con.execute("""SELECT subject_id, predicate, value, evidence FROM facts
                            WHERE subject_type='document' AND source_type='drawing' AND status='active'
                              AND predicate IN ('title','material','weight_g')"""):
        ev = json.loads(r["evidence"] or "{}")
        v = r["value"] or ("(empty)" if ev.get("empty_on_sheet") else "(illegible)")
        tb.setdefault(r["subject_id"], {})[r["predicate"]] = v.replace("\n", " / ")
    link = {}
    for r in con.execute("""SELECT d.document_id, d.status, GROUP_CONCAT(l.row_index) AS rows
                            FROM link_decisions d LEFT JOIN doc_bom_links l
                              ON l.document_id = d.document_id AND l.method IN ('curated','correction') AND l.status != 'rejected'
                            GROUP BY d.document_id"""):
        link[r["document_id"]] = f"{r['status']}: {r['rows']}" if r["rows"] else r["status"]
    lines = ["id | file name | subsystem | quality | 3D | title-block TITLE | title-block MATERIAL | WEIGHT [g] | BOM link"]
    for d in kb.list_documents(con):
        t = tb.get(d["id"], {})
        lines.append(f"{d['id']} | {d['title']} | {d['subsystem']} | "
                     f"{'DEGRADED scan' if d['distribution'] == 'degraded-only' else 'clean'} | "
                     f"{'yes' if d['has_model'] else 'no'} | {t.get('title', '-')} | {t.get('material', '-')} | "
                     f"{t.get('weight_g', '-')} | {link.get(d['id'], 'not reviewed')}")
    return "\n".join(lines)


def _bom_index(con) -> str:
    rows = con.execute(
        """SELECT b.row_index, b.name,
                  MAX(CASE WHEN f.predicate='part_family' THEN f.value END) AS family,
                  MAX(CASE WHEN f.predicate='type' THEN f.value END) AS type,
                  MAX(CASE WHEN f.predicate='material' THEN f.value END) AS material,
                  MAX(CASE WHEN f.predicate='supplier' THEN f.value END) AS supplier,
                  MAX(CASE WHEN f.predicate='vv_state' THEN f.value END) AS vv,
                  MAX(CASE WHEN f.predicate='cost_dkk' THEN f.value END) AS cost,
                  MAX(f.source_type = 'correction') AS corrected
           FROM bom_rows b
           LEFT JOIN facts f ON f.subject_type='bom_row' AND f.subject_id = CAST(b.row_index AS TEXT)
                             AND f.status='active'
           GROUP BY b.row_index ORDER BY b.row_index""").fetchall()
    lines = ["row | name | family | type | material | supplier | V&V | cost DKK (recorded snapshot)   "
             "(blank = not recorded; * = has accepted correction)"]
    for r in rows:
        cells = [r["name"], r["family"], r["type"], r["material"], r["supplier"], r["vv"], r["cost"]]
        lines.append(f"{r['row_index']}{'*' if r['corrected'] else ''} | " + " | ".join(c or "" for c in cells))
    return "\n".join(lines)


CHECK_LABEL = {"text_layer_match": "confirmed by PDF text layer", "repeat_read_agrees": "two readings agree",
               "repeat_read_disagrees": "two readings DISAGREE", "not_in_text_layer": "NOT found in text layer"}


def _facts_block(facts: list[dict]) -> str:
    out = []
    for f in facts:
        ev = f.get("evidence") or {}
        if f["value"] is None and ev.get("empty_on_sheet"):
            value = "(box present but EMPTY on the sheet)"
        elif f["value"] is None:
            value = "(ILLEGIBLE on the sheet)"
        else:
            value = f["value"].replace("\n", " / ")
        line = f"  - {f['predicate']}: {value}  [{f['source_ref']}]"
        notes = []
        if ev.get("legibility") and ev["legibility"] != "clear":
            notes.append(f"legibility {ev['legibility']}")
        if ev.get("check") in CHECK_LABEL:
            notes.append(CHECK_LABEL[ev["check"]])
        if ev.get("alternative_reading") is not None:
            notes.append(f"other reading: {ev['alternative_reading']!r}")
        if notes:
            line += "  (" + "; ".join(notes) + ")"
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
    for q in d["quality"]:
        parts.append(f"sheet legibility p{q['page']} (vision read): {q['legibility']}"
                     + (f" - {q['issues']}" if q["issues"] else ""))
    parts.append(_links_block(d))
    if d["consistency"]:
        parts.append("drawing vs BOM consistency:\n" + "\n".join(_consistency_line(c) for c in d["consistency"]))
    parts.append("title-block fields read from the drawing:\n" + _facts_block(d["facts"]))
    if d["annotations"]:
        for kind in ("dimension", "callout"):
            items = [a for a in d["annotations"] if a["kind"] == kind]
            if items:
                parts.append(f"{kind}s as written on the sheet [cite as {d['id']} p<page>]:\n" + "\n".join(
                    f"  - p{a['page']} {a['text'].replace(chr(10), ' / ')}"
                    + (f"  ({a['feature']})" if a.get("feature") and a["feature"] != "unknown" else "")
                    + (f"  [legibility {a['legibility']}]" if a["legibility"] != "clear" else "")
                    for a in items))
    else:  # no vision extraction yet: fall back to the raw text layer
        for p in d["pages_text"]:
            if p["has_text_layer"] and p["text"]:
                txt = re.sub(r"\s+", " ", p["text"])[:DRAWING_TEXT_CHARS]
                parts.append(f"extracted text layer, page {p['page']} (raw, unordered): {txt}")
            else:
                parts.append(f"page {p['page']}: no text layer (raster scan); contents not machine-read yet")
    return "\n".join(parts)


def _links_block(d: dict) -> str:
    dec = d.get("link_decision")
    curated = [l for l in d["bom_links"] if l["method"] in REVIEWED]
    if dec:
        head = f"BOM link (reviewed decision: {dec['status'].upper()}): {dec['rationale']}"
        rows = "; ".join(f"row {l['row_index']} {l['name']}" for l in curated)
        return head + (f"\n  linked rows: {rows}" if rows else "\n  linked rows: none - no BOM row describes this part")
    fuzzy = [l for l in d["bom_links"] if l["method"] not in REVIEWED]
    return "BOM link: not reviewed; filename fuzzy candidates only (unconfirmed): " + (
        "; ".join(f"row {l['row_index']} {l['name']} (score {round(l['score'])})" for l in fuzzy) or "none")


VERDICT = {"agree": "AGREE", "drawing_more_specific": "AGREE (drawing more specific)", "conflict": "CONFLICT",
           "missing_on_drawing": "NOT STATED ON DRAWING", "missing_in_bom": "NOT RECORDED IN BOM"}


def _consistency_line(c: dict) -> str:
    return (f"  - {c['field']}: {VERDICT.get(c['verdict'], c['verdict'])} - drawing {c['document_id']}: "
            f"{(c['drawing_value'] or '-')!r} [{c['drawing_ref'] or '-'}] vs BOM row {c['row_index']}: "
            f"{(c['bom_value'] or '-')!r} [{c['bom_ref'] or '-'}] ({c['detail']})")


def _row_focus(con, row_index: int) -> str:
    r = kb.get_bom_row(con, row_index)
    parts = [f"### BOM row {row_index} - {r['name']}",
             "facts (active and superseded, with sources):\n" + _facts_block(r["facts"])]
    if r["drawings"]:
        parts.append("drawings: " + "; ".join(
            f"{d['document_id']} {d['title']} ({d['status']}{', ' + d['method'] if d['method'] != 'curated' else ''})"
            for d in r["drawings"]))
    else:
        parts.append("drawings: none linked")
    if r["consistency"]:
        parts.append("drawing vs BOM consistency:\n" + "\n".join(_consistency_line(c) for c in r["consistency"]))
    if r["interfaces_with"] or r["referenced_by"]:
        out = "; ".join(f"{i['name_in_bom']} (row {i['row_index']}, {i['part_family']})" if i["row_index"]
                        else f"{i['name_in_bom']} (no matching BOM row)" for i in r["interfaces_with"])
        inc = "; ".join(f"{i['name']} (row {i['row_index']}, {i['part_family']})" for i in r["referenced_by"])
        parts.append(f"interfaces [BOM row {row_index} 'Interface with' column]: {out or 'none recorded'}"
                     + (f"\n  named as an interface by: {inc}" if inc else ""))
    return "\n".join(parts)


def _discrepancies(con) -> str:
    probs = consistency.problems(con)
    counts = {}
    for r in con.execute("SELECT field, verdict, COUNT(*) n FROM consistency_checks GROUP BY 1, 2"):
        counts[f"{r['field']} {r['verdict']}"] = r["n"]
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "no linked pairs"
    return (f"checked pairs (reviewed links only): {summary}\n"
            + ("\n".join(_consistency_line(c) for c in probs) or "(no conflicts or missing values)"))


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
        found = kb.find(con, text, limit=8)
        # keep strong matches only, and only those close to the best one (drops generic "plate" hits)
        best = max((h["score"] for h in found), default=0)
        found = [h for h in found if h["score"] >= max(FOCUS_MIN_SCORE, best - RELATIVE_WINDOW)]
        hits += found
        if docs or rows or found:
            break  # the latest message names something; don't drag in the older one
    for h in hits:
        (docs if h["kind"] == "drawing" else rows).append(h["id"] if h["kind"] == "drawing" else h["row_index"])
    # Pull in reviewed counterparts so drawing<->BOM questions have both sides (and a BOM-named
    # part still opens its drawing).
    linked = lambda l: l["method"] in REVIEWED and l["status"] in ("confirmed", "probable")
    for row in list(rows):
        docs += [d["document_id"] for d in kb.get_bom_row(con, row)["drawings"] if linked(d)]
    docs = list(dict.fromkeys(docs))[:MAX_FOCUS_DOCS]
    for doc_id in docs:
        rows += [l["row_index"] for l in kb.get_document(con, doc_id)["bom_links"] if linked(l)]
    rows = list(dict.fromkeys(rows))[:MAX_FOCUS_ROWS]
    return docs, rows, hits


SUPPLIER_Q = re.compile(r"supplier|supply|manufactur|make (it|this|the)|who (could|can) (make|produce|machine|build)|"
                        r"vendor|source (it|this)|buy|order from|fabricat|machine shop|job shop", re.I)


def build_evidence(con, messages: list[dict]) -> tuple[str, list[str], list[int], list[dict]]:
    docs, rows, hits = focus_targets(con, messages)
    focus = [_doc_focus(con, d) for d in docs] + [_row_focus(con, r) for r in rows]
    if SUPPLIER_Q.search(messages[-1]["content"]):
        from .. import suppliers
        focus += [suppliers.summary_for_chat(con, d) for d in docs]
    package = "\n\n".join([
        "## DRAWING INDEX\n" + _drawing_index(con),
        "## BOM INDEX (pinned snapshot; active values incl. accepted corrections)\n" + _bom_index(con),
        "## FOCUS EVIDENCE (parts matched to the question)\n" + ("\n\n".join(focus) or "(no specific part matched)"),
        "## DRAWING vs BOM DISCREPANCIES (machine-wide)\n" + _discrepancies(con),
        "## CORRECTIONS\n" + _corrections(con),
    ])
    return package, docs, rows, hits
