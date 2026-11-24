"""Potential suppliers for a drawn part, beyond the BOM's recorded supplier.

1. profile()   What the part needs, from extracted evidence only: material (drawing + BOM), processes
               implied by callouts/notes (each with the text that implies it), size envelope, quantity.
2. internal()  The recorded supplier(s) for the linked BOM row(s), and other BOM suppliers that supplied
               parts of the same material class (capability evidence from the same snapshot).
3. search()    Web search via Gemini with Google Search grounding: companies that offer those processes
               in that material. Each suggestion carries its basis, the search sources, and whether its
               website appeared in the search results. Cached in data/suppliers/<DOC>.json with the
               retrieval date: a search result is a lead, not a verified capability or a quote.

Sends a description of the part (material, processes, size, quantity; no drawing images) to Google.
"""
import json
import re
from datetime import datetime, timezone

from . import config, consistency
from .config import DATA

CACHE = DATA / "suppliers"
REGION = "Denmark or nearby EU countries"  # project context: DTU, costs recorded in DKK
CAVEAT = ("Search results are leads, not verified capabilities, quotes or availability. They reflect the web on "
          "the retrieval date; contact the company to confirm. Recorded BOM suppliers are a pinned snapshot.")

# (process, regex over callouts/notes/dimensions, why) - deliberately simple and explainable
RULES = [
    ("drilling", r"thru( all)?|gennem", "through-hole callout"),
    ("thread tapping", r"\bM\d+(\s*x\s*[\d.]+)?\s*-\s*6H|tap for|helicoil", "threaded-hole callout"),
    ("countersinking", r"⌵|x\s*90°|countersink|undersænkning", "countersink callout"),
    ("counterboring", r"⌴|counterbore", "counterbore callout"),
    ("precision machining (fits/tolerances)", r"\b[HhJjNn]\d{1,2}\b\s*[+-]?\d|±0[,.]0\d", "fit or tight tolerance (e.g. H7, ±0,05)"),
    ("fine surface finishing", r"\bRa\s*\d", "surface roughness requirement"),
    ("welding", r"weld|svejs", "welding note"),
    ("weld/press nuts", r"weld nuts|press nuts|pem", "weld-nut note"),
    ("o-ring groove machining", r"o-ring", "o-ring groove note"),
]


def _texts(con, doc_id):
    ann = [dict(r) for r in con.execute("SELECT kind, text FROM drawing_annotations WHERE document_id=?", (doc_id,))]
    facts = {r["predicate"]: r["value"] for r in con.execute(
        """SELECT predicate, value FROM facts WHERE subject_type='document' AND subject_id=? AND status='active'
           AND source_type='drawing' AND value IS NOT NULL""", (doc_id,))}
    return ann, facts


def profile(con, doc_id: str) -> dict | None:
    doc = con.execute("SELECT id, title, subsystem FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        return None
    ann, facts = _texts(con, doc_id)
    note = facts.get("note") or ""
    rows = [dict(r) for r in con.execute(
        """SELECT b.row_index, b.name FROM doc_bom_links l JOIN bom_rows b USING(row_index)
           WHERE l.document_id=? AND l.method IN ('curated','correction') AND l.status IN ('confirmed','probable')""", (doc_id,))]
    dmat, dref = consistency.drawing_material(con, doc_id)
    bmats = [_fact(con, r["row_index"], "material") for r in rows]
    classes = consistency.material_classes(" ".join(x for x in [dmat or ""] + [m or "" for m in bmats]))

    processes = []
    flat = lambda t: re.sub(r"\s*\n\s*", " / ", t or "")
    corpus = [(a["text"], f"{a['kind']}: {flat(a['text'])}") for a in ann] + [(note, f"note: {flat(note)}")]
    for name, pattern, why in RULES:
        hit = next((src for text, src in corpus if text and re.search(pattern, text, re.I)), None)
        if hit:
            processes.append({"process": name, "evidence": f"{why} - {hit[:90]}"})
    # form of the part, from title/notes/material
    name = f"{doc['title']} {facts.get('title') or ''}".lower()
    metal = classes & {"stainless steel", "aluminium", "steel"}
    welded_box = re.search(r"weld|svejs", note, re.I) and re.search(r"box|kasse|thin", f"{name} {note}", re.I)
    sheet = metal and (re.search(r"\b([0-3](?:[.,]\d)?)\s*mm\b", note) or welded_box)
    if classes & {"silicone", "elastomer"}:
        processes.insert(0, {"process": "gasket cutting (die / waterjet / knife)", "evidence": f"material {dmat or bmats}"})
    elif sheet or "flange" in note.lower():
        processes.insert(0, {"process": "sheet-metal laser cutting and bending",
                             "evidence": f"thin sheet / welded box in note: {flat(note)[:80]!r}"})
    elif re.search(r"ring|cylinder|shaft|cylinder", name):
        processes.insert(0, {"process": "CNC turning", "evidence": f"rotational part ({doc['title']})"})
        processes.insert(1, {"process": "CNC milling", "evidence": "holes/features off the axis"})
    else:
        processes.insert(0, {"process": "CNC milling", "evidence": f"machined plate/block ({doc['title']})"})

    nums = []
    for a in ann:
        if a["kind"] == "dimension":
            m = re.search(r"(\d+(?:[.,]\d+)?)", a["text"].replace("Ø", ""))
            if m:
                nums.append(float(m.group(1).replace(",", ".")))
    qty = consistency.drawing_quantity(doc["title"], facts.get("title"), note)
    amount = [_fact(con, r["row_index"], "amount") for r in rows]
    return {
        "document_id": doc_id, "part": facts.get("title") or doc["title"], "subsystem": doc["subsystem"],
        "bom_rows": rows,
        "material": {"drawing": dmat, "drawing_ref": dref, "bom": [m for m in bmats if m], "classes": sorted(classes)},
        "processes": processes,
        "largest_dimension_mm": max(nums) if nums else None,
        "quantity": {"drawing": f"{qty[0]}" if qty and qty[0] == qty[1] else (f"{qty[0]}-{qty[1]}" if qty else None),
                     "bom": [a for a in amount if a]},
    }


def internal(con, prof: dict) -> dict:
    recorded = []
    for r in prof["bom_rows"]:
        recorded.append({"row": r["row_index"], "name": r["name"], "supplier": _fact(con, r["row_index"], "supplier"),
                         "order": _fact(con, r["row_index"], "supplier_order"), "cost_dkk": _fact(con, r["row_index"], "cost_dkk")})
    similar = {}
    if prof["material"]["classes"]:
        for r in con.execute("""SELECT s.subject_id AS row, s.value AS supplier, m.value AS material, n.name
                                FROM facts s JOIN facts m ON m.subject_id = s.subject_id AND m.subject_type='bom_row'
                                    AND m.predicate='material' AND m.status='active'
                                JOIN bom_rows n ON n.row_index = CAST(s.subject_id AS INTEGER)
                                WHERE s.subject_type='bom_row' AND s.predicate='supplier' AND s.status='active'"""):
            if consistency.material_classes(r["material"]) & set(prof["material"]["classes"]):
                similar.setdefault(r["supplier"], []).append(f"row {r['row']} {r['name']}")
    return {"recorded": recorded,
            "same_material_in_bom": [{"supplier": s, "rows": rows[:6], "count": len(rows)}
                                     for s, rows in sorted(similar.items(), key=lambda kv: -len(kv[1]))]}


def cached(doc_id: str) -> dict | None:
    f = CACHE / f"{doc_id}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def search(con, doc_id: str) -> dict:
    from google import genai
    from google.genai import types

    prof = profile(con, doc_id)
    if not prof:
        raise KeyError(doc_id)
    procs = ", ".join(p["process"] for p in prof["processes"])
    mat = prof["material"]["drawing"] or ", ".join(prof["material"]["bom"]) or "unspecified"
    qty = prof["quantity"]["drawing"] or ", ".join(prof["quantity"]["bom"]) or "1"
    # Step 1: grounded web search, answered in prose (asking for JSON here makes the model skip searching).
    search_prompt = f"""Search the web for 3 to 5 manufacturing companies in {REGION} that could make this custom
part as a small batch, and say what each company's website states about these capabilities.
Part: {prof['part']} (subsystem {prof['subsystem']} of a metal laser powder-bed-fusion machine).
Material: {mat}. Processes needed: {procs}. Largest dimension about {prof['largest_dimension_mm'] or 'unknown'} mm.
Quantity: {qty}.
For each company give: name, website, city and country, which of the processes/material it states it offers,
and one sentence on why it fits. Only include companies you found in your search results."""
    client = genai.Client(api_key=config.GEMINI_API_KEY,
                          http_options=types.HttpOptions(timeout=120_000, retry_options=types.HttpRetryOptions(attempts=1)))
    resp, model_used = None, None
    last = None
    for attempt in range(2):  # a second try if the model answered without searching
        for model in [config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS]:
            try:
                resp = client.models.generate_content(
                    model=model, contents=search_prompt,
                    config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())],
                                                       temperature=0.2))
                model_used = model
                break
            except Exception as e:  # noqa: BLE001
                last = e
                if not any(s in str(e) for s in ("503", "429", "500", "504", "UNAVAILABLE", "DEADLINE")):
                    raise
        if resp is None:
            raise RuntimeError(f"search unavailable: {last}")
        gm = resp.candidates[0].grounding_metadata if resp.candidates else None
        if gm and gm.grounding_chunks:
            break
    sources = [{"title": ch.web.title, "uri": ch.web.uri} for ch in (gm.grounding_chunks or [])] if gm else []

    # Step 2: structure the grounded answer (no new facts may be added here).
    items = []
    if sources:
        schema = {"type": "object", "properties": {"suggestions": {"type": "array", "items": {
            "type": "object", "properties": {
                "name": {"type": "string"}, "website": {"type": "string"}, "location": {"type": "string"},
                "matches": {"type": "array", "items": {"type": "string"}}, "basis": {"type": "string"}},
            "required": ["name", "basis"]}}}, "required": ["suggestions"]}
        structured = client.models.generate_content(
            model=model_used,
            contents=("Convert this search answer into JSON. Use only information present in the text; do not add "
                      "companies or details.\n\n" + (resp.text or "")),
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema,
                                               temperature=0, thinking_config=types.ThinkingConfig(thinking_level="LOW")))
        items = json.loads(structured.text or "{}").get("suggestions", [])
    domains = {s["title"].lower().removeprefix("www.") for s in sources if s.get("title")}
    for it in items:
        host = re.sub(r"^https?://(www\.)?", "", (it.get("website") or "").lower()).split("/")[0]
        it["in_search_results"] = bool(host) and any(host == d or host.endswith("." + d) or d.endswith("." + host) for d in domains)
    out = {
        "document_id": doc_id, "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "region": REGION, "queries": list(gm.web_search_queries or []) if gm else [],
        "profile_used": {"material": mat, "processes": procs, "quantity": qty},
        "suggestions": items, "sources": sources, "caveat": CAVEAT,
        "searched": bool(sources),
        "note": None if sources else "The model did not perform a web search, so no suggestions are shown. Try again.",
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{doc_id}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def summary_for_chat(con, doc_id: str) -> str:
    """Compact text for chat evidence: profile, recorded supplier, cached search (if any)."""
    prof = profile(con, doc_id)
    if not prof:
        return ""
    inn = internal(con, prof)
    lines = [f"supplier profile for {doc_id} (derived from extracted evidence): material "
             f"{prof['material']['drawing'] or prof['material']['bom'] or 'unstated'}; processes: "
             + "; ".join(f"{p['process']} ({p['evidence'][:60]})" for p in prof["processes"])]
    for r in inn["recorded"]:
        lines.append(f"  recorded supplier (BOM row {r['row']}, pinned snapshot): {r['supplier'] or 'not recorded'}")
    if inn["same_material_in_bom"]:
        lines.append("  other BOM suppliers of the same material class: " + "; ".join(
            f"{s['supplier']} ({s['count']} rows)" for s in inn["same_material_in_bom"][:5]))
    c = cached(doc_id)
    if c:
        lines.append(f"  web search for potential suppliers (retrieved {c['retrieved_at'][:10]}, leads only):")
        for s in c["suggestions"]:
            lines.append(f"    - {s.get('name')} ({s.get('location')}, {s.get('website')}): {s.get('basis')}"
                         + ("" if s.get("in_search_results") else " [website NOT seen in search results]"))
    else:
        lines.append("  no web search run yet for this part (the user can run one in the drawing's Suppliers tab)")
    return "\n".join(lines)


def _fact(con, row, predicate):
    r = con.execute("""SELECT value FROM facts WHERE subject_type='bom_row' AND subject_id=? AND predicate=?
                       AND status='active' ORDER BY id DESC LIMIT 1""", (str(row), predicate)).fetchone()
    return r["value"] if r else None
