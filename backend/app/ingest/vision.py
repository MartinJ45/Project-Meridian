"""Vision pass: read each drawing sheet with Gemini and save structured, located fields.

    python -m app.ingest.vision                 # all drawings missing an extraction
    python -m app.ingest.vision --only D-012 D-025
    python -m app.ingest.vision --force         # redo all

Each page is rendered to PNG and sent with a strict JSON schema. The model must transcribe
exactly what is written (no guessing), mark every field's legibility, and give a bounding
box so answers can cite a region of the sheet. For clean PDFs the text layer is sent as a
hint; degraded scans are read from pixels only.

Output: data/extracted/vision/<DOC_ID>.json (committed), loaded by `app.ingest.run`.
Sends drawing page images to the Google Gemini API (disclosed in RUNNING.md).
"""
import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pymupdf

from .. import config
from ..config import EXTRACTED, ROOT
from ..db import connect

VISION_DIR = EXTRACTED / "vision"
PROMPT_VERSION = "drawing-fields-v1"
DPI = 200

LEGIBILITY = {"type": "string", "enum": ["clear", "partial", "illegible"]}
BOX = {"type": "array", "items": {"type": "integer"},
       "description": "[ymin, xmin, ymax, xmax] on a 0-1000 grid over the page image"}


def _field(desc: str) -> dict:
    return {"type": "object", "description": desc,
            "properties": {"value": {"type": "string", "nullable": True}, "legibility": LEGIBILITY, "box_2d": BOX},
            "required": ["value", "legibility"]}


TITLE_BLOCK_FIELDS = {
    "title": "TITLE/DESCRIPTION box text",
    "material": "MATERIAL box text (designation/alloy as written)",
    "weight_g": "WEIGHT [g] value as written",
    "scale": "SCALE value, e.g. 1:2",
    "sheet": "SHEET x OF y",
    "date": "DATE / drawn date as written",
    "company": "organisation name from the COMPANY box only (no person names, emails or phone numbers)",
    "finish": "FINISH box text",
    "general_tolerance": "general tolerance standard, e.g. DIN ISO 2768-1 m",
    "paper_size": "sheet size, e.g. A3",
    "note": "NOTE box text (all lines, as written, any language)",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "sheet_legibility": {"type": "string", "enum": ["clear", "partly_legible", "mostly_illegible"]},
        "legibility_issues": {"type": "string", "description": "what is hard to read and where; empty if clear"},
        "title_block": {"type": "object", "properties": {k: _field(v) for k, v in TITLE_BLOCK_FIELDS.items()},
                        "required": list(TITLE_BLOCK_FIELDS)},
        "views": {"type": "array", "items": {"type": "string"},
                  "description": "views on the sheet, e.g. 'front view', 'section A-A', 'isometric'"},
        "dimensions": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "exactly as written incl. tolerance, e.g. '25,0 +0,1/-0,5'"},
                "feature": {"type": "string", "description": "what it measures if clear from the drawing, else 'unknown'"},
                "view": {"type": "string"},
                "legibility": LEGIBILITY,
                "box_2d": BOX,
            },
            "required": ["text", "feature", "legibility"]}},
        "callouts": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "hole/thread/countersink/GD&T/note callout exactly as written"},
                "legibility": LEGIBILITY,
                "box_2d": BOX,
            },
            "required": ["text", "legibility"]}},
    },
    "required": ["sheet_legibility", "legibility_issues", "title_block", "views", "dimensions", "callouts"],
}

PROMPT = """You are reading one sheet of a mechanical fabrication drawing for an engineering knowledge base.
Transcribe; do not interpret or guess.

Rules:
- Copy text exactly as written, keeping decimal commas, symbols (Ø, ±, °, ⌴, ↧) and the original
  language (often Danish). Do not translate or convert units.
- If a value cannot be read with confidence, set value to null and legibility "illegible". Never
  fill in a plausible value. If only part is readable, write the readable part, mark unreadable
  characters with [?], and set legibility "partial".
- If a title-block box is present but empty, value null with legibility "clear".
- box_2d is [ymin, xmin, ymax, xmax] of the text on a 0-1000 grid over the whole image.
- dimensions: every dimension value on the views (not the title block), up to 60. feature says what
  it measures only when the drawing makes that clear (e.g. "overall length", "bore diameter");
  otherwise "unknown".
- callouts: hole, thread, countersink/counterbore, GD&T and note callouts with leaders, as written.
- Do not transcribe personal names, email addresses or phone numbers anywhere.
- sheet_legibility: "clear" if all text reads cleanly, "partly_legible" if some text is uncertain,
  "mostly_illegible" if most small text cannot be read.
{text_hint}"""


def _render_pages(path, dpi: int = DPI) -> list[tuple[int, bytes]]:
    pdf = pymupdf.open(ROOT / path)
    return [(i, page.get_pixmap(dpi=dpi).tobytes("png")) for i, page in enumerate(pdf, start=1)]


def _layer_text(doc_id: str, page: int) -> str:
    f = EXTRACTED / f"{doc_id}.json"
    if not f.exists():
        return ""
    pages = json.loads(f.read_text(encoding="utf-8"))["pages"]
    p = next((p for p in pages if p["page"] == page), None)
    return p["text"] if p and p["has_text_layer"] else ""


def _text_hint(doc_id: str, page: int) -> str:
    text = _layer_text(doc_id, page)
    if not text:
        return "\nThis sheet is a raster scan with no text layer: read it from the image only."
    return ("\nThe PDF's embedded text layer for this page is below (unordered; use it to confirm characters, "
            "but locations and associations must come from the image):\n" + text[:4000])


def _call(image: bytes, prompt: str) -> tuple[dict, dict, str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY,
                          http_options=types.HttpOptions(timeout=180_000,
                                                         retry_options=types.HttpRetryOptions(attempts=1)))
    last = None
    for attempt in range(3):  # passes over the model list, like the chat fallback
        for model in [config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS]:
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=[types.Part.from_bytes(data=image, mime_type="image/png"), prompt],
                    config=types.GenerateContentConfig(
                        temperature=0, response_mime_type="application/json", response_schema=SCHEMA,
                        thinking_config=types.ThinkingConfig(thinking_level="MEDIUM")),
                )
                u = resp.usage_metadata
                usage = {"prompt_tokens": u.prompt_token_count, "output_tokens": u.candidates_token_count,
                         "thinking_tokens": u.thoughts_token_count}
                return json.loads(resp.text), usage, model
            except Exception as e:  # noqa: BLE001
                last = e
                msg = str(e)
                if not any(s in msg for s in ("503", "429", "500", "504", "UNAVAILABLE", "DEADLINE", "timed out")):
                    raise
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"all models failed: {last}")


EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<![\d,.])(?:\+?\d[\d ]{6,}\d)(?![\d,.])")


def _scrub(value):
    """Drop personal contact details that may appear in title blocks."""
    if not isinstance(value, str):
        return value
    value = PHONE.sub("", EMAIL.sub("", value))
    return "\n".join(l for l in (s.strip() for s in value.splitlines()) if l) or None


def _norm(s: str) -> str:
    """Comparison key: case/space-insensitive, unify decimal separators and diameter glyphs."""
    s = (s or "").lower().replace(",", ".").replace("⌀", "ø").replace("∅", "ø")
    return re.sub(r"\s+", "", s)


def _items(page: dict):
    """Every transcribed item on a page as (kind, key, obj) with obj['value'|'text'] to check."""
    for k, f in page["title_block"].items():
        yield "title_block", k, f
    for i, d in enumerate(page["dimensions"]):
        yield "dimension", i, d
    for i, c in enumerate(page["callouts"]):
        yield "callout", i, c


def _tokens(s: str) -> list[str]:
    """Words and numbers only. Text layers often drop symbol glyphs (Ø, ⊥) and reorder tolerances,
    so the check is: every word/number the model read also occurs in the text layer."""
    return re.findall(r"[0-9]+(?:[.,][0-9]+)?|[^\W\d_]+", (s or "").lower().replace(",", "."))


def _verify_with_text_layer(page: dict, text: str) -> None:
    """Clean PDFs: a transcription whose tokens all occur in the embedded text layer is confirmed."""
    hay = set(_tokens(text))
    for _, _, obj in _items(page):
        val = obj.get("value") if "value" in obj else obj.get("text")
        if not val:
            obj["check"] = "empty"
            continue
        toks = _tokens(val)
        if not toks:
            obj["check"] = "symbols_only"  # e.g. a GD&T frame like '⊥ A' with nothing to compare
            continue
        missing = [t for t in toks if t not in hay]
        obj["check"] = "text_layer_match" if not missing else "not_in_text_layer"
        if missing:
            obj["missing_tokens"] = missing


def _verify_by_repeat(page: dict, second: dict) -> None:
    """Degraded scans: compare with an independent second reading; disagreement downgrades legibility."""
    def val(o):
        return o.get("value") if "value" in o else o.get("text")
    for k, f in page["title_block"].items():
        other = second["title_block"].get(k, {})
        a, b = val(f), val(other)
        if _norm(a or "") == _norm(b or ""):
            f["check"] = "repeat_read_agrees"
        else:
            f["check"] = "repeat_read_disagrees"
            f["alternative"] = b
            if f["legibility"] == "clear":
                f["legibility"] = "partial"
    others = {_norm(val(o)) for o in second["dimensions"] + second["callouts"]}
    for kind in ("dimensions", "callouts"):
        for o in page[kind]:
            if _norm(val(o)) in others:
                o["check"] = "repeat_read_agrees"
            else:
                o["check"] = "repeat_read_disagrees"
                if o["legibility"] == "clear":
                    o["legibility"] = "partial"
    page["repeat_read"] = {"dpi": SECOND_DPI, "sheet_legibility": second["sheet_legibility"]}


SECOND_DPI = 150


def extract(doc: dict) -> dict:
    t0 = time.time()
    pages = []
    usage_total = {"prompt_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
    model_used = None

    def add(usage):
        for k in usage_total:
            usage_total[k] += usage.get(k) or 0

    second_images = dict(_render_pages(doc["path"], SECOND_DPI)) if doc["distribution"] == "degraded-only" else {}
    for page, image in _render_pages(doc["path"]):
        hint = _text_hint(doc["id"], page)
        result, usage, model_used = _call(image, PROMPT.format(text_hint=hint))
        add(usage)
        for _, _, obj in _items(result):
            for key in ("value", "text"):
                if key in obj:
                    obj[key] = _scrub(obj[key])
        layer = _layer_text(doc["id"], page)
        if layer:
            _verify_with_text_layer(result, layer)
        elif page in second_images:
            second, usage2, _ = _call(second_images[page], PROMPT.format(text_hint=hint))
            add(usage2)
            for _, _, obj in _items(second):
                for key in ("value", "text"):
                    if key in obj:
                        obj[key] = _scrub(obj[key])
            _verify_by_repeat(result, second)
        pages.append({"page": page, **result})
    return {
        "document_id": doc["id"],
        "distribution": doc["distribution"],
        "extractor": {"model": model_used, "prompt_version": PROMPT_VERSION, "dpi": DPI,
                      "verification": (f"repeat read at {SECOND_DPI} dpi" if second_images
                                       else "embedded text layer" if any(_layer_text(doc["id"], p["page"]) for p in pages)
                                       else "none"),
                      "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "seconds": round(time.time() - t0, 1), "usage": usage_total},
        "pages": pages,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="drawing ids, e.g. D-012")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY is not set in .env")

    VISION_DIR.mkdir(parents=True, exist_ok=True)
    con = connect()
    docs = [dict(r) for r in con.execute("SELECT id, path, distribution FROM documents ORDER BY id")]
    con.close()
    todo = [d for d in docs if (not args.only or d["id"] in args.only)
            and (args.force or not (VISION_DIR / f"{d['id']}.json").exists())]
    print(f"extracting {len(todo)} drawing(s) with up to {args.workers} in parallel")

    def work(d):
        try:
            out = extract(d)
            (VISION_DIR / f"{d['id']}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
            p = out["pages"][0]
            items = [o for _, _, o in _items(p)]
            ill = sum(1 for o in items if o["legibility"] == "illegible")
            part = sum(1 for o in items if o["legibility"] == "partial")
            checks = {}
            for o in items:
                checks[o.get("check", "-")] = checks.get(o.get("check", "-"), 0) + 1
            return (f"{d['id']} ok {out['extractor']['seconds']:>5}s sheet={p['sheet_legibility']:<16} "
                    f"dims={len(p['dimensions']):<3} callouts={len(p['callouts']):<3} partial={part} illegible={ill} "
                    f"checks={checks}")
        except Exception as e:  # noqa: BLE001
            return f"{d['id']} FAILED {type(e).__name__}: {str(e)[:200]}"

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for line in pool.map(work, todo):
            print(line, flush=True)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
