"""Load what was extracted from each drawing PDF.

Pass 1 (here, local, free): PyMuPDF text layer + word boxes -> data/extracted/D-0xx.json.
Clean upstream PDFs have one; the eight degraded scans do not.

Pass 2 (app.ingest.vision, Gemini, run once): title-block fields, dimensions and callouts
with sheet locations, legibility and an independent check (text-layer match for clean PDFs,
a second reading for degraded scans) -> data/extracted/vision/D-0xx.json.

Both outputs are committed, so building the database needs no API key.
"""
import json

import pymupdf as fitz

from ..config import EXTRACTED, ROOT


def extract_text_layer(doc_row: dict) -> dict:
    pdf = fitz.open(ROOT / doc_row["path"])
    pages = []
    for i, page in enumerate(pdf, start=1):
        words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
        pages.append({
            "page": i,
            "width": page.rect.width,
            "height": page.rect.height,
            "has_text_layer": bool(words),
            "text": page.get_text("text").strip(),
            "words": [[round(w[0], 1), round(w[1], 1), round(w[2], 1), round(w[3], 1), w[4]] for w in words],
        })
    return {
        "document_id": doc_row["id"],
        "extractor": f"pymupdf-{fitz.VersionBind}",
        "needs_vision": not any(p["has_text_layer"] for p in pages),
        "pages": pages,
        "fields": {},  # filled by the vision pass
    }


def run(con, force: bool = False) -> int:
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    docs = [dict(r) for r in con.execute("SELECT * FROM documents ORDER BY id")]
    for d in docs:
        out = EXTRACTED / f"{d['id']}.json"
        if out.exists() and not force:
            data = json.loads(out.read_text(encoding="utf-8"))
        else:
            data = extract_text_layer(d)
            out.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        for p in data["pages"]:
            con.execute(
                "INSERT OR REPLACE INTO drawing_pages (document_id, page, width, height, has_text_layer, text) VALUES (?,?,?,?,?,?)",
                (d["id"], p["page"], p["width"], p["height"], int(p["has_text_layer"]), p["text"]),
            )
        load_vision(con, d["id"])
    return len(docs)


VERIFIED = {"text_layer_match", "repeat_read_agrees"}


def confidence(obj: dict) -> float:
    """Simple, explainable score: legibility as read, raised when an independent check agrees."""
    leg, check = obj.get("legibility"), obj.get("check")
    if leg == "illegible":
        return 0.0
    if leg == "partial":
        return 0.5
    return 0.95 if check in VERIFIED else 0.8


def load_vision(con, doc_id: str) -> bool:
    f = EXTRACTED / "vision" / f"{doc_id}.json"
    if not f.exists():
        return False
    data = json.loads(f.read_text(encoding="utf-8"))
    ex = data["extractor"]
    extractor = f"{ex['model']} {ex['prompt_version']} {ex['extracted_at'][:10]} (check: {ex.get('verification')})"
    for p in data["pages"]:
        page = p["page"]
        con.execute("INSERT OR REPLACE INTO drawing_quality (document_id, page, legibility, issues, extractor) VALUES (?,?,?,?,?)",
                    (doc_id, page, p["sheet_legibility"], p.get("legibility_issues") or "", extractor))
        for name, field in p["title_block"].items():
            value = field.get("value")
            empty = value is None and field.get("legibility") == "clear"
            evidence = {"page": page, "box_2d": field.get("box_2d"), "legibility": field.get("legibility"),
                        "check": field.get("check"), "empty_on_sheet": empty, "extractor": extractor}
            if field.get("alternative") is not None:
                evidence["alternative_reading"] = field["alternative"]
            con.execute(
                """INSERT INTO facts (subject_type, subject_id, predicate, value, source_type, source_ref, confidence, evidence)
                   VALUES ('document', ?, ?, ?, 'drawing', ?, ?, ?)""",
                (doc_id, name, value, f"{doc_id} p{page} title block", confidence(field), json.dumps(evidence)))
        for kind, items in (("dimension", p["dimensions"]), ("callout", p["callouts"])):
            for o in items:
                con.execute(
                    """INSERT INTO drawing_annotations (document_id, page, kind, feature, text, legibility, box_2d)
                       VALUES (?,?,?,?,?,?,?)""",
                    (doc_id, page, kind, o.get("feature"), o.get("text") or "",
                     o.get("legibility") if o.get("check") not in ("not_in_text_layer",) else "partial",
                     json.dumps(o.get("box_2d"))))
    return True
