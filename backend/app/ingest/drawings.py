"""Extract what we can from each drawing PDF.

Pass 1 (here, local, free): PyMuPDF text layer + word boxes. Clean upstream PDFs usually
have one; the eight degraded scans do not, and are flagged `needs_vision=True`.

Pass 2 (TODO, Gemini vision): read title block, dimensions, material, notes from page
images — especially the degraded scans — and write the result into the same JSON file
under "fields", each with a page/bbox and a legibility/confidence value. The JSON files
in data/extracted/ are committed so the app runs without an API key.
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
        for name, field in data.get("fields", {}).items():
            con.execute(
                """INSERT INTO facts (subject_type, subject_id, predicate, value, source_type, source_ref, confidence)
                   VALUES ('document', ?, ?, ?, 'drawing', ?, ?)""",
                (d["id"], name, field.get("value"), f"{d['id']} p{field.get('page', 1)}", field.get("confidence")),
            )
    return len(docs)
