"""HTTP API + static frontend. Run from backend/:  uvicorn app.main:app --port 8000"""
import mimetypes

# Windows' registry often maps .js/.mjs to text/plain, which browsers refuse for module scripts.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("model/gltf-binary", ".glb")

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chats, config
from . import knowledge as kb
from .chat.agent import run_turn
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
    chats.add_message(ccon, chat_id, "assistant", result["reply"],
                      {k: result[k] for k in ("attachments", "trace", "mode", "latency_ms")})
    return {"chat_id": chat_id, **result}


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
