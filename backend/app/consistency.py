"""Compare what a drawing says with what its linked BOM row(s) say.

Material: both sides are mapped to coarse classes (aluminium, stainless steel, steel, silicone, ...)
so "EN-AW 5005" vs "Aluminium" counts as agreement with the drawing being more specific, while
"aluminium" vs "Stainless steel" is a conflict. The drawing's title-block MATERIAL box is used
first; if it is empty, a material named in the NOTE box is used (and said so).

Quantity: only when the sheet states one ("x2", "2 stk", "3 styk", "1-3 stk").

Uses *active* facts, so an accepted correction changes the outcome; recomputed on every
ingest and after every accepted correction.
"""
import json
import re

CLASSES = [  # order matters: stainless before steel
    ("stainless steel", r"stainless|rustfri|aisi\s*3\d\d|non-magnetic"),
    ("aluminium", r"\balu\b|alu\.|alumin|en[\s-]?aw|aw-\d|\b(6061|6063|6082|7075|5005)\b|3\.3315"),
    ("silicone", r"silicon|silikone"),
    ("steel", r"(?<!stainless )\bsteel\b|\bstål\b"),
    ("polymer", r"polymer|plastic|pom|nylon|pla\b|petg"),
    ("elastomer", r"elastomer|rubber|gummi"),
    ("ceramic", r"ceramic|keramisk"),
]
# A grade/alloy designation (6061, EN-AW 5005, AISI 316, 7075-T6) is more specific than a class name.
# Plain numbers such as "2mm" are not.
ALLOY = re.compile(r"\b\d{4}\b|aisi\s*\d|en[\s-]?aw|aw-\d|3\.3315|-t\d\b", re.I)


def material_classes(text: str | None) -> set[str]:
    t = (text or "").lower()
    found = set()
    for name, pattern in CLASSES:
        if re.search(pattern, t):
            found.add(name)
    if "stainless steel" in found and not re.search(r"(?<!stainless )\bsteel\b", t.replace("stainless steel", "")):
        found.discard("steel")
    return found


def drawing_quantity(*texts: str) -> tuple[int, int] | None:
    """(min, max) pieces stated on the sheet or in the file name, else None."""
    for t in texts:
        t = (t or "").lower()
        m = re.search(r"(\d+)\s*-\s*(\d+)\s*(?:stk|styk)", t)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = re.search(r"(\d+)\s*(?:stk|styk)\b", t) or re.search(r"\bx\s?(\d+)\b", t)
        if m:
            n = int(m.group(1))
            return n, n
    return None


def _active(con, subject_type, subject_id, predicate):
    r = con.execute("""SELECT value, source_ref, evidence FROM facts WHERE subject_type=? AND subject_id=?
                       AND predicate=? AND status='active' ORDER BY id DESC LIMIT 1""",
                    (subject_type, str(subject_id), predicate)).fetchone()
    return (r["value"], r["source_ref"], json.loads(r["evidence"] or "{}")) if r else (None, None, {})


def drawing_material(con, doc_id: str) -> tuple[str | None, str | None]:
    value, ref, _ = _active(con, "document", doc_id, "material")
    if value:
        return value, f"{ref} (MATERIAL box)"
    note, ref, _ = _active(con, "document", doc_id, "note")
    if note and material_classes(note):
        return note.replace("\n", " / "), f"{ref} (NOTE box; MATERIAL box empty)"
    return None, None


def _verdict(drawing: str | None, bom: str | None) -> tuple[str, str]:
    if not drawing:
        return "missing_on_drawing", "the drawing does not state a material"
    if not bom:
        return "missing_in_bom", "the BOM row has no material recorded"
    d, b = material_classes(drawing), material_classes(bom)
    if not d or not b:
        return "conflict" if d != b else "agree", "could not classify one side; compare the text directly"
    if d & b:
        extra = f"; BOM also lists {', '.join(sorted(b - d))}" if b - d else ""
        if ALLOY.search(drawing) and not ALLOY.search(bom):
            return "drawing_more_specific", f"same class ({', '.join(sorted(d & b))}); drawing gives the grade{extra}"
        return "agree", f"same class ({', '.join(sorted(d & b))}){extra}"
    return "conflict", f"drawing says {', '.join(sorted(d))}, BOM says {', '.join(sorted(b))}"


def run(con) -> int:
    con.execute("DELETE FROM consistency_checks")
    links = con.execute("""SELECT document_id, row_index FROM doc_bom_links
                           WHERE method IN ('curated','correction') AND status IN ('confirmed','probable')""").fetchall()
    by_doc: dict[str, list[int]] = {}
    for l in links:
        by_doc.setdefault(l["document_id"], []).append(l["row_index"])
    n = 0
    for doc_id, rows in by_doc.items():
        dmat, dref = drawing_material(con, doc_id)
        title = con.execute("SELECT title FROM documents WHERE id=?", (doc_id,)).fetchone()["title"]
        sheet_title, _, _ = _active(con, "document", doc_id, "title")
        note, note_ref, _ = _active(con, "document", doc_id, "note")
        qty = drawing_quantity(title, sheet_title, note)
        amounts = {}
        for row in rows:
            bmat, bref, _ = _active(con, "bom_row", row, "material")
            verdict, detail = _verdict(dmat, bmat)
            con.execute("""INSERT INTO consistency_checks (document_id, row_index, field, drawing_value, drawing_ref,
                           bom_value, bom_ref, verdict, detail) VALUES (?,?,?,?,?,?,?,?,?)""",
                        (doc_id, row, "material", dmat, dref, bmat, bref, verdict, detail))
            n += 1
            amt, aref, _ = _active(con, "bom_row", row, "amount")
            amounts[row] = (amt, aref)
        if qty:
            total = sum(int(a) for a, _ in amounts.values() if a and a.isdigit())
            lo, hi = qty
            stated = f"{lo}" if lo == hi else f"{lo}-{hi}"
            combined = len(rows) > 1
            ok = lo <= total <= hi
            for row, (amt, aref) in amounts.items():
                detail = (f"sheet states {stated}; BOM {'total over rows ' + ', '.join(map(str, rows)) if combined else 'amount'} = {total}")
                con.execute("""INSERT INTO consistency_checks (document_id, row_index, field, drawing_value, drawing_ref,
                               bom_value, bom_ref, verdict, detail) VALUES (?,?,?,?,?,?,?,?,?)""",
                            (doc_id, row, "quantity", stated, f"{doc_id} title / note", amt, aref,
                             "agree" if ok else "conflict", detail))
                n += 1
    return n


def for_document(con, doc_id: str) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM consistency_checks WHERE document_id=? ORDER BY field, row_index", (doc_id,))]


def for_row(con, row_index: int) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM consistency_checks WHERE row_index=? ORDER BY field", (row_index,))]


def problems(con) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT * FROM consistency_checks WHERE verdict IN ('conflict','missing_in_bom','missing_on_drawing') ORDER BY verdict, document_id")]
