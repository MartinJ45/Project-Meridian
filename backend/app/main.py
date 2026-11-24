"""HTTP API + static frontend. Run from backend/:  uvicorn app.main:app --port 8000"""
import mimetypes

# Windows' registry often maps .js/.mjs to text/plain, which browsers refuse for module scripts.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("model/gltf-binary", ".glb")

import json

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chats, config, graph, metrics, suppliers, uploads
from . import knowledge as kb
from .chat.agent import run_turn, run_turn_events
from .db import connect

app = FastAPI(title="Project Meridian")


def get_con():
    if not config.DB_PATH.exists():
        raise HTTPException(503, "Database not built. Run: python -m app.ingest.run")
    con = connect()
    try:
        yield con
    finally:
        con.close()


@app.get("/api/health")
def health(con=Depends(get_con)):
    # Deliberately does not name the LLM provider or model: users only need online/offline.
    return {"ok": True, "llm_configured": bool(config.GEMINI_API_KEY), **kb.stats(con)}


@app.get("/api/documents")
def documents(con=Depends(get_con)):
    return kb.list_documents(con)


@app.get("/api/documents/{doc_id}")
def document(doc_id: str, con=Depends(get_con)):
    return kb.get_document(con, doc_id) or _404(doc_id)


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: str, con=Depends(get_con)):
    row = con.execute("SELECT path FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        _404(doc_id)
    return FileResponse(config.ROOT / row["path"], media_type="application/pdf")


@app.get("/api/bom")
def bom(q: str = "", limit: int = 100, con=Depends(get_con)):
    return kb.search_bom(con, q, limit)


@app.get("/api/bom/{row_index}")
def bom_row(row_index: int, con=Depends(get_con)):
    return kb.get_bom_row(con, row_index) or _404(row_index)


def get_chats_con():
    con = chats.open_db()
    try:
        yield con
    finally:
        con.close()


class ChatRequest(BaseModel):
    message: str
    chat_id: str | None = None  # omit to start a new chat


@app.post("/api/chat")
def chat(req: ChatRequest, con=Depends(get_con), ccon=Depends(get_chats_con)):
    """One chat turn. History comes from the stored chat, and both sides of the turn are saved."""
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "message is empty")
    if req.chat_id:
        if not chats.get_chat(ccon, req.chat_id):
            _404(req.chat_id)
        chat_id = req.chat_id
    else:
        chat_id = chats.create_chat(ccon, message)["id"]
    msgs = chats.history(ccon, chat_id) + [{"role": "user", "content": message}]
    chats.add_message(ccon, chat_id, "user", message)  # saved first, so a failed turn still shows the question
    result = run_turn(con, msgs)
    result.pop("_internal", None)  # provider/model details stay server-side
    chats.add_message(ccon, chat_id, "assistant", result["reply"],
                      {k: result[k] for k in ("attachments", "trace", "mode", "latency_ms")})
    return {"chat_id": chat_id, **result}


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    """Same as /api/chat, but streams newline-delimited JSON events while the reply is written:
    start {chat_id}, delta {text}, reset (discard streamed text), done {chat_id, reply, attachments, ...},
    error {message}."""
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "message is empty")
    if not config.DB_PATH.exists():
        raise HTTPException(503, "Database not built. Run: python -m app.ingest.run")
    ccon = chats.open_db()
    if req.chat_id and not chats.get_chat(ccon, req.chat_id):
        ccon.close()
        _404(req.chat_id)
    chat_id = req.chat_id or chats.create_chat(ccon, message)["id"]
    msgs = chats.history(ccon, chat_id) + [{"role": "user", "content": message}]
    chats.add_message(ccon, chat_id, "user", message)  # saved first, so a failed turn still shows the question

    def events():
        con = connect()
        line = lambda e: json.dumps(e, ensure_ascii=False) + "\n"
        try:
            yield line({"type": "start", "chat_id": chat_id})
            for ev in run_turn_events(con, msgs):
                if ev["type"] != "done":
                    yield line(ev)
                    continue
                result = ev["result"]
                result.pop("_internal", None)  # provider/model details stay server-side
                chats.add_message(ccon, chat_id, "assistant", result["reply"],
                                  {k: result[k] for k in ("attachments", "trace", "mode", "latency_ms")})
                yield line({"type": "done", "chat_id": chat_id, **result})
        except Exception as e:  # noqa: BLE001
            yield line({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            con.close()
            ccon.close()

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/documents/upload")
async def upload_drawing(file: UploadFile = File(...), subsystem: str = Form("Unassigned")):
    """Add a new drawing. Returns at once; processing continues in the background."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "please upload a PDF")
    data = await file.read()
    if len(data) > 30 * 1024 * 1024:
        raise HTTPException(413, "PDF is larger than 30 MB")
    try:
        item = uploads.save_upload(data, file.filename, subsystem)
    except ValueError as e:
        raise HTTPException(400, str(e))
    uploads.start(item["id"])
    return {**item, "status": uploads.status(item["id"])}


@app.get("/api/uploads/{uid}")
def upload_status(uid: str):
    return uploads.status(uid) or _404(uid)


@app.get("/api/metrics")
def knowledge_metrics(con=Depends(get_con)):
    """Current knowledge health, its history after each reviewed change, and evaluation runs."""
    return {"now": metrics.snapshot(con), "history": metrics.history(), "eval_runs": metrics.eval_runs()}


@app.get("/api/suppliers/{doc_id}")
def supplier_info(doc_id: str, con=Depends(get_con)):
    prof = suppliers.profile(con, doc_id) or _404(doc_id)
    return {"profile": prof, "internal": suppliers.internal(con, prof), "search": suppliers.cached(doc_id),
            "caveat": suppliers.CAVEAT, "search_available": bool(config.GEMINI_API_KEY)}


@app.post("/api/suppliers/{doc_id}/search")
def supplier_search(doc_id: str, con=Depends(get_con)):
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "web search needs an API key (offline mode)")
    try:
        return suppliers.search(con, doc_id)
    except KeyError:
        _404(doc_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"supplier search failed: {e}")


@app.get("/api/graph")
def knowledge_graph(con=Depends(get_con)):
    return graph.build(con)


@app.get("/api/chats")
def chat_list(ccon=Depends(get_chats_con)):
    return chats.list_chats(ccon)


@app.get("/api/chats/{chat_id}")
def chat_get(chat_id: str, ccon=Depends(get_chats_con)):
    return chats.get_chat(ccon, chat_id) or _404(chat_id)


@app.delete("/api/chats/{chat_id}")
def chat_delete(chat_id: str, ccon=Depends(get_chats_con)):
    if not chats.delete_chat(ccon, chat_id):
        _404(chat_id)
    return {"deleted": chat_id}


class Review(BaseModel):
    note: str = ""


class Proposal(BaseModel):
    subject_type: str          # bom_row | document
    subject_id: str
    predicate: str             # e.g. material, amount, bom_link
    new_value: str
    rationale: str = ""


@app.post("/api/corrections")
def propose(body: Proposal, con=Depends(get_con)):
    """Propose a correction from the UI (same review flow as chat proposals)."""
    if body.subject_type not in kb.SUBJECT_TYPES or not body.new_value.strip():
        raise HTTPException(400, "subject_type must be bom_row or document, and new_value is required")
    return kb.propose_correction(con, body.subject_type, body.subject_id.strip(), body.predicate.strip(),
                                 body.new_value.strip(), body.rationale, "ui")


@app.get("/api/corrections")
def corrections(status: str | None = None, con=Depends(get_con)):
    return kb.list_corrections(con, status)


@app.post("/api/corrections/{cid}/accept")
def accept(cid: int, body: Review, con=Depends(get_con)):
    return _review(con, cid, True, body.note)


@app.post("/api/corrections/{cid}/reject")
def reject(cid: int, body: Review, con=Depends(get_con)):
    return _review(con, cid, False, body.note)


@app.get("/api/audit")
def audit(con=Depends(get_con)):
    return kb.audit_log(con)


def _review(con, cid, accept, note):
    try:
        return kb.review_correction(con, cid, accept, note)
    except KeyError:
        _404(cid)
    except ValueError as e:
        raise HTTPException(409, str(e))


def _404(what):
    raise HTTPException(404, f"not found: {what}")


config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/files/models", StaticFiles(directory=config.MODELS_DIR), name="models")
app.mount("/files/diagrams", StaticFiles(directory=config.DATASET / "context" / "diagrams"), name="diagrams")
if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
