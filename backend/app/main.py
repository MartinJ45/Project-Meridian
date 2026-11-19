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

from . import config
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
    return {"ok": True, "gemini_configured": bool(config.GEMINI_API_KEY), "model": config.GEMINI_MODEL, **kb.stats(con)}


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


class ChatRequest(BaseModel):
    messages: list[dict]  # [{role: "user"|"assistant", content: str}]


@app.post("/api/chat")
def chat(req: ChatRequest, con=Depends(get_con)):
    if not req.messages:
        raise HTTPException(400, "messages is empty")
    return run_turn(con, req.messages)


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
