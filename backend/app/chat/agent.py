"""Chat turn: retrieve evidence in Python, then ONE Gemini request that returns JSON.

    question -> retrieve.build_evidence() -> Gemini (JSON: reply, open_documents, correction)
             -> open drawings/3D, file any proposed correction for review

One request per turn (no tool loop) keeps latency to a single round trip, and the model
can only see evidence we retrieved, so answers stay grounded in extracted knowledge.
Without GEMINI_API_KEY, or when every model is unavailable, the turn falls back to offline
matches and still opens the drawing.
"""
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from .. import config, graph
from .. import knowledge as kb
from .context import TurnContext
from .retrieve import SUPPLIER_Q, build_evidence

SYSTEM_PROMPT = """You are Meridian, an assistant for engineers exploring the design evidence of the
OpenLPBF v2 metal laser powder-bed-fusion machine (subsystems: Box, Powder, Recoater, Optical,
Gas Flow, Z-axis). Each user turn ends with an EVIDENCE package extracted from the drawings and the
BOM. Answer ONLY from that evidence and earlier turns; never from general knowledge about the machine.

Rules:
- Cite every factual claim inline: [BOM row N], [D-0xx p1], or [correction N].
- Keep the source explicit: "the BOM records..." vs "the drawing shows...".
- Supplier, order number, cost and status values come from a pinned BOM snapshot; present them as
  recorded, not as current availability or price.
- 3D models are reconstructions from 2D drawing evidence, not native CAD. Say so when one is shown.
- Drawing-to-BOM links have a reviewed status: CONFIRMED (title names the part), PROBABLE (judgement; say
  so and give the reason), or NONE (no BOM row describes the part). Unreviewed fuzzy candidates are not links.
- Use the "drawing vs BOM consistency" results for agreement/conflict questions; quote both values and refs.
- Interfaces come from the BOM's 'Interface with' column (few rows fill it in); say when none are recorded.
- Drawing fields were read from the sheet by a vision pass, each with legibility and an independent check
  (PDF text layer, or a second reading for degraded scans). Distinguish "the box is EMPTY on the sheet"
  from "ILLEGIBLE". Treat partial legibility, disagreeing readings or missing checks as uncertain and say so.
- When the drawing and the BOM both state a value (e.g. material), compare them and point out disagreement
  or a difference in specificity (e.g. BOM "Aluminium" vs drawing "EN-AW 5005"); never silently merge them.
- If the evidence is missing, noisy, or conflicting, say so and abstain rather than guess.
- SUPERSEDED facts were replaced by an accepted correction: answer from the active value, and when
  relevant mention the change and the original value with its source.
- open_documents: list the drawing ids (e.g. "D-012") for the part(s) the user is asking about, so the
  app opens the sheet (and its 3D, if any). Empty for questions not about a specific part. Never paste URLs.
- Potential suppliers: use the "supplier profile" evidence. Separate (1) the supplier the BOM records (pinned
  snapshot), (2) other BOM suppliers of the same material, and (3) web-search leads with their retrieval date.
  Give the basis for each match (material/process) and say leads are unverified and may be out of date. If no
  search has been run, say the user can run one in the drawing's Suppliers tab; never invent company names.
- open_graph: set (e.g. "D-018", "row 10", "aluminium", "Box") when the question is about relationships -
  interfaces, what connects to what, which parts share a material/supplier/subsystem - or the user asks for
  the graph. Otherwise null.
- correction: only when the user asserts a recorded value is wrong. Fill subject_type "bom_row"
  (subject_id = row number) or "document" (subject_id = "D-0xx"), predicate (e.g. material, supplier,
  cost_dkk, vv_state, amount), new_value and rationale. In the reply, say it is pending human review in the
  Review tab and answers will not change until it is accepted. Otherwise set correction to null.
  Link corrections: when the user says a drawing belongs to a different BOM row (or none), or confirms a
  probable link, use subject_type "document", subject_id the drawing id, predicate "bom_link" and
  new_value the BOM row number(s) comma-separated, or "none".
- Be concise. Use short markdown lists or tables where helpful."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "open_documents": {"type": "array", "items": {"type": "string"}},
        "open_graph": {"type": "string", "nullable": True,
                       "description": "drawing id, 'row N', material class or subsystem to show in the knowledge graph"},
        "correction": {
            "type": "object",
            "nullable": True,
            "properties": {
                "subject_type": {"type": "string", "enum": ["bom_row", "document"]},
                "subject_id": {"type": "string"},
                "predicate": {"type": "string"},
                "new_value": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["subject_type", "subject_id", "predicate", "new_value"],
        },
    },
    "required": ["reply", "open_documents"],
}

log = logging.getLogger("uvicorn.error")
HISTORY_MESSAGES = 8
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gemini")

# Errors worth trying the next model for: overload, rate limit, timeout, transient server errors.
RETRYABLE = ("503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "DEADLINE", "timed out", "Timeout")


def run_turn(con, messages: list[dict]) -> dict:
    ctx = TurnContext(con=con)
    t0 = time.time()
    attempts: list[dict] = []
    if not config.GEMINI_API_KEY:
        reply, mode = _offline_turn(ctx, messages[-1]["content"]), "offline"
    else:
        evidence, docs, rows, hits = build_evidence(con, messages)
        ctx.log("retrieve", {"focus_drawings": docs, "focus_bom_rows": rows},
                f"{len(evidence)} chars of evidence; top matches: "
                + ", ".join(f"{h.get('id') or 'row ' + str(h.get('row_index'))} ({h['score']})" for h in hits[:4]))
        result, mode = None, None
        for model in [config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS]:
            if attempts and time.time() - t0 > config.GEMINI_TURN_BUDGET_S:
                attempts.append({"model": model, "ok": False, "seconds": 0, "error": "skipped: turn time budget used up"})
                break
            t = time.time()
            remaining = max(5.0, config.GEMINI_TURN_BUDGET_S - (t - t0))
            try:
                # Hard wall-clock cap; on timeout the worker thread is abandoned and its result ignored.
                result, usage = _POOL.submit(_ask_gemini, messages, evidence, model).result(timeout=remaining)
                mode = "online"
                attempts.append({"model": model, "ok": True, "seconds": round(time.time() - t, 1), **usage})
                break
            except Exception as e:  # noqa: BLE001 - surfaced to the UI below
                msg = f"Timeout: no answer within {remaining:.0f}s" if isinstance(e, FutureTimeout) else f"{type(e).__name__}: {e}"
                attempts.append({"model": model, "ok": False, "seconds": round(time.time() - t, 1), "error": msg[:300]})
                if not any(s in msg for s in RETRYABLE):
                    break  # e.g. 404 model not found, 400 bad key: another model will not help
        # Provider/model details go to the server log only; the UI just sees online/offline.
        for a in attempts:
            log.info("llm attempt %s", a)
        if result is None:
            busy = any("Timeout" in a.get("error", "") or "DEADLINE" in a.get("error", "") for a in attempts)
            reason = "took longer than a minute" if busy else "is unavailable"
            reply = (f"**The assistant {reason} right now.** Try again shortly; here are the closest offline matches.\n\n"
                     + _offline_turn(ctx, messages[-1]["content"], header=False))
            mode = "offline-fallback"
        else:
            reply = _apply(ctx, result, hits, messages[-1]["content"])
    return {
        "reply": reply,
        "attachments": ctx.attachments,
        "trace": ctx.trace,
        "mode": mode,
        "latency_ms": round((time.time() - t0) * 1000),
        # For evaluation/logging only; removed from HTTP responses (it names the provider/model).
        "_internal": {"attempts": attempts},
    }


def _ask_gemini(messages: list[dict], evidence: str, model: str) -> tuple[dict, dict]:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=config.GEMINI_API_KEY,
        # Fail fast and let our fallback chain handle overload, instead of long SDK-internal retries.
        http_options=types.HttpOptions(timeout=int(config.GEMINI_TIMEOUT_S * 1000),
                                       retry_options=types.HttpRetryOptions(attempts=1)),
    )
    history = [m for m in messages[:-1] if m.get("content")][-HISTORY_MESSAGES:]
    contents = [types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part(text=m["content"])])
                for m in history]
    contents.append(types.Content(role="user", parts=[types.Part(
        text=f"QUESTION:\n{messages[-1]['content']}\n\nEVIDENCE:\n{evidence}")]))
    gen_config = dict(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.2,
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
    )
    if config.GEMINI_THINKING:
        gen_config["thinking_config"] = types.ThinkingConfig(thinking_level=config.GEMINI_THINKING.upper())
    resp = client.models.generate_content(model=model, contents=contents,
                                          config=types.GenerateContentConfig(**gen_config))
    u = resp.usage_metadata
    usage = {"prompt_tokens": getattr(u, "prompt_token_count", None),
             "thinking_tokens": getattr(u, "thoughts_token_count", None),
             "output_tokens": getattr(u, "candidates_token_count", None)} if u else {}
    try:
        return json.loads(resp.text or "{}"), usage
    except json.JSONDecodeError:
        return {"reply": resp.text or "(no text returned)", "open_documents": []}, usage


def _apply(ctx: TurnContext, result: dict, hits: list[dict], question: str = "") -> str:
    """Act on the model's structured answer: open drawings, file a correction for review."""
    valid = {r["id"] for r in ctx.con.execute("SELECT id FROM documents")}
    requested = [d.strip().upper() for d in result.get("open_documents") or []]
    for doc_id in requested:
        if doc_id in valid:
            ctx.attach_document(doc_id)
    ctx.log("open_documents", {"requested": requested}, [a["document_id"] for a in ctx.attachments])
    # Safety net for "chat must open the drawing": a near-exact drawing name match opens even if
    # the model forgot to list it.
    if SUPPLIER_Q.search(question or "") and any(a["type"] == "drawing" for a in ctx.attachments):
        for a in ctx.attachments:
            if a["type"] == "drawing":
                a["tab"] = "suppliers"  # open the Suppliers tab for this drawing
                break
    if not ctx.attachments and hits and hits[0]["kind"] == "drawing" and hits[0]["score"] >= 90:
        ctx.attach_document(hits[0]["id"])
        ctx.log("auto_open", {"document_id": hits[0]["id"], "score": hits[0]["score"]}, "opened")

    focus = graph.resolve(ctx.con, result.get("open_graph"))
    if focus:
        ctx.attachments.append({"type": "graph", "focus": focus, "label": result["open_graph"]})
        ctx.log("open_graph", {"ref": result["open_graph"]}, focus)

    reply = result.get("reply") or "(empty reply)"
    c = result.get("correction")
    if c and c.get("subject_type") in kb.SUBJECT_TYPES and c.get("new_value"):
        subject_id = str(c["subject_id"]).strip().upper() if c["subject_type"] == "document" else str(c["subject_id"]).strip()
        proposal = kb.propose_correction(ctx.con, c["subject_type"], subject_id, c.get("predicate", "").strip(),
                                         c["new_value"], c.get("rationale", ""), "chat")
        ctx.log("propose_correction", c, f"correction {proposal['id']} pending review"
                + (" (already proposed)" if proposal.get("duplicate") else ""))
        failed = [k["name"] for k in proposal["check_report"]["checks"] if not k["ok"]]
        if proposal.get("duplicate"):
            reply += f"\n\n_This change is already pending review as correction #{proposal['id']}; no new request was filed"
        else:
            reply += f"\n\n_Filed as correction #{proposal['id']} (pending review)"
        reply += f"; automated checks flagged: {', '.join(failed)}._" if failed else "._"
    return reply


def _offline_turn(ctx: TurnContext, question: str, header: bool = True) -> str:
    hits = kb.find(ctx.con, question, limit=5)
    ctx.log("find_parts", {"query": question}, hits)
    lines = ["**Offline mode:** showing the closest matches, no generated answer.", ""] if header else []
    for h in hits:
        if h["kind"] == "drawing":
            lines.append(f"- Drawing {h['id']} - {h['title']} ({h['subsystem']}, {h['distribution']}) - match {h['score']}")
        else:
            lines.append(f"- BOM row {h['row_index']} - {h['name']} ({h['part_family']}) - match {h['score']}")
    # Open a drawing if the best hit is one, or the best hit is a BOM row with a strong drawing link.
    top = hits[0] if hits and hits[0]["score"] >= 70 else None
    if top and top["kind"] == "drawing":
        ctx.attach_document(top["id"])
    elif top:
        link = ctx.con.execute(
            "SELECT document_id FROM doc_bom_links WHERE row_index = ? AND score >= 90 AND status != 'rejected' "
            "ORDER BY score DESC LIMIT 1", (top["row_index"],)).fetchone()
        if link:
            ctx.attach_document(link["document_id"])
            lines.append(f"\nOpened {link['document_id']} (candidate drawing link for BOM row {top['row_index']}).")
    return "\n".join(lines)
