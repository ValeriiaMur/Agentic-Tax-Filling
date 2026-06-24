"""FastAPI app: web chat, W-2 upload, observation trail, and 1040 download.

State is held per session in-memory (a dict of session_id -> TaxAgent). For a
single-instance prototype this is the simplest thing that demonstrates the
chat-loop pillar; a production system would use a shared store.
"""

from __future__ import annotations

import os
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from .agent import TaxAgent

HERE = os.path.dirname(__file__)
STATIC = os.path.join(HERE, "..", "static")
ASSETS = os.path.join(HERE, "..", "assets")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(HERE, "..", "_outputs"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="Agentic Tax-Filing Assistant", version="1.0.0")

_SESSIONS: dict[str, TaxAgent] = {}

GREETING = (
    "Hi! I'm here to help you fill out your 2025 federal tax return (Form 1040) "
    "from your W-2. It only takes a couple of minutes and a few questions. "
    "To begin, upload your W-2 (photo or PDF) or just type in your Box 1 wages "
    "and Box 2 federal withholding.\n\n"
    "(This is an educational demo with fake data — not tax advice or a real filing.)"
)


def _get_agent(session_id: str) -> TaxAgent:
    agent = _SESSIONS.get(session_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    return agent


class MessageIn(BaseModel):
    session_id: str
    message: str


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


@app.get("/healthz")
def health():
    return {"ok": True, "sessions": len(_SESSIONS)}


@app.post("/api/session")
def new_session():
    sid = uuid.uuid4().hex[:12]
    _SESSIONS[sid] = TaxAgent(sid, OUTPUT_DIR)
    _SESSIONS[sid].obs.emit("state", "session_started")
    return {"session_id": sid, "greeting": GREETING}


@app.post("/api/message")
def message(body: MessageIn):
    agent = _get_agent(body.session_id)
    return JSONResponse(agent.handle_message(body.message))


@app.post("/api/w2")
async def upload_w2(
    session_id: str = Form(...),
    text: str = Form(default=""),
    file: UploadFile | None = File(default=None),
):
    agent = _get_agent(session_id)
    if file is not None:
        content = await file.read()
        media = file.content_type or "image/png"
        return JSONResponse(agent.ingest_w2(image_bytes=content, media_type=media))
    if text.strip():
        return JSONResponse(agent.ingest_w2(text=text))
    raise HTTPException(status_code=400, detail="Provide a W-2 file or text.")


@app.get("/api/events/{session_id}")
def events(session_id: str):
    agent = _get_agent(session_id)
    return {"events": agent.obs.as_list()}


@app.get("/api/download/{session_id}")
def download(session_id: str):
    agent = _get_agent(session_id)
    if not agent.pdf_path or not os.path.exists(agent.pdf_path):
        raise HTTPException(status_code=404, detail="No completed form yet.")
    return FileResponse(
        agent.pdf_path, media_type="application/pdf",
        filename="Form_1040_2025_completed.pdf",
    )


@app.get("/api/sample-w2")
def sample_w2():
    path = os.path.join(ASSETS, "sample_w2.png")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No sample available.")
    return FileResponse(path, media_type="image/png", filename="sample_w2.png")
