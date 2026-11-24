"""Corrections to drawing <-> BOM links (correction predicate 'bom_link' on a drawing).

new_value: comma-separated BOM row numbers ("81" or "91,93"), or "none" when no BOM row describes the
part. Proposing the *current* rows is a confirmation: on acceptance a probable link becomes confirmed.

Accepting never deletes the previous decision: earlier links are marked 'rejected' (kept, visible as
superseded) and the new links are stored with method 'correction' and a pointer to the correction.
"""
import re

from . import consistency


def parse_rows(value: str) -> list[int] | None:
    v = (value or "").strip().lower()
    if v in ("none", "no row", "no bom row", "-"):
        return []
    rows = [int(x) for x in re.findall(r"\d{1,3}", v)]
    return rows or None


def current(con, doc_id: str) -> tuple[list[int], str | None]:
    rows = [r[0] for r in con.execute(
        """SELECT row_index FROM doc_bom_links WHERE document_id=? AND method IN ('curated','correction')
           AND status IN ('confirmed','probable') ORDER BY row_index""", (doc_id,))]
    dec = con.execute("SELECT status FROM link_decisions WHERE document_id=?", (doc_id,)).fetchone()
    return rows, dec["status"] if dec else None


def check(con, doc_id: str, new_value: str, add) -> dict:
    """Verification before acceptance: does the drawing's evidence fit the proposed BOM row(s)?"""
    rows = parse_rows(new_value)
    cur_rows, cur_status = current(con, doc_id)
    report = {"current_facts": [{"value": ", ".join(map(str, cur_rows)) or "none",
                                 "source_ref": f"link decision ({cur_status or 'not reviewed'})"}]}
    if rows is None:
        add("value format", False, f"expected BOM row numbers or 'none', got {new_value!r}")
        return report
    if sorted(rows) == cur_rows:
        add("changes something", True,
            f"same rows as the current {cur_status} link: accepting CONFIRMS it" if cur_status == "probable"
            else f"same rows as the current {cur_status} link: no change")
    else:
        add("changes something", True, f"link would change from {cur_rows or 'none'} to {rows or 'none'}")
    if not rows:
        add("drawing evidence", True, "proposes that no BOM row describes this drawing")
        return report

    doc = con.execute("SELECT subsystem FROM documents WHERE id=?", (doc_id,)).fetchone()
    dmat, dref = consistency.drawing_material(con, doc_id)
    dcls = consistency.material_classes(dmat)
    fam_sub = _family_subsystems(con)
    for r in rows:
        b = con.execute("SELECT name FROM bom_rows WHERE row_index=?", (r,)).fetchone()
        if not b:
            add("row exists", False, f"BOM row {r} does not exist")
            continue
        add("row exists", True, f"BOM row {r}: {b['name']}")
        bmat = _active(con, r, "material")
        bcls = consistency.material_classes(bmat)
        if dcls and bcls:
            ok = bool(dcls & bcls)
            add("material fits", ok, f"drawing {dmat!r} [{dref}] vs BOM row {r} {bmat!r}"
                + ("" if ok else " -> DIFFERENT material classes"))
        else:
            add("material fits", True, f"cannot compare (drawing: {dmat or 'not stated'}, BOM: {bmat or 'not recorded'})")
        fam = _active(con, r, "part_family")
        expected = fam_sub.get(fam)
        if expected:
            ok = expected == doc["subsystem"]
            add("subsystem fits", ok, f"BOM family {fam!r} is drawn in {expected}; this drawing is in {doc['subsystem']}"
                + ("" if ok else " -> MISMATCH"))
    return report


def apply(con, doc_id: str, new_value: str, cid: int) -> None:
    rows = parse_rows(new_value) or []
    con.execute("""UPDATE doc_bom_links SET status='rejected',
                   rationale = COALESCE(rationale, '') || ' [superseded by correction ' || ? || ']'
                   WHERE document_id=? AND method IN ('curated','correction') AND status != 'rejected'""", (cid, doc_id))
    for r in rows:
        con.execute("""INSERT OR REPLACE INTO doc_bom_links (document_id, row_index, score, method, status, rationale)
                       VALUES (?,?,100,'correction','confirmed',?)""",
                    (doc_id, r, f"set by reviewed correction {cid}"))
    status = "confirmed" if rows else "none"
    old = con.execute("SELECT status, rationale FROM link_decisions WHERE document_id=?", (doc_id,)).fetchone()
    note = f"Set by reviewed correction {cid}." + (f" Previously {old['status']}: {old['rationale']}" if old else "")
    con.execute("INSERT OR REPLACE INTO link_decisions (document_id, status, rationale) VALUES (?,?,?)",
                (doc_id, status, note))


def _active(con, row: int, predicate: str):
    r = con.execute("""SELECT value FROM facts WHERE subject_type='bom_row' AND subject_id=? AND predicate=?
                       AND status='active' ORDER BY id DESC LIMIT 1""", (str(row), predicate)).fetchone()
    return r["value"] if r else None


def _family_subsystems(con) -> dict[str, str]:
    """BOM family -> the subsystem most of its reviewed drawings are in (derived from current links)."""
    counts: dict[str, dict[str, int]] = {}
    for r in con.execute("""SELECT f.value AS fam, d.subsystem FROM doc_bom_links l
                            JOIN documents d ON d.id = l.document_id
                            JOIN facts f ON f.subject_type='bom_row' AND f.subject_id = CAST(l.row_index AS TEXT)
                                        AND f.predicate='part_family' AND f.status='active'
                            WHERE l.method IN ('curated','correction') AND l.status IN ('confirmed','probable')"""):
        counts.setdefault(r["fam"], {}).setdefault(r["subsystem"], 0)
        counts[r["fam"]][r["subsystem"]] += 1
    return {fam: max(subs, key=subs.get) for fam, subs in counts.items()}
