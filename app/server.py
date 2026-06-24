"""FastAPI app for the free-text agentic tax-filing assistant.

A minimal web chat (per the brief: keep the front end minimal, spend effort on
the harness). Every turn goes through `TaxSession`, so the four pillars stay
enforced and observable on the server; the browser holds no tax logic.

Endpoints:
  POST /api/session            start a session, get the greeting
  POST /api/message            one free-text chat turn
  POST /api/w2                 upload a W-2 (any file) or paste figures
  POST /api/sample             load the bundled fake W-2 (demo convenience)
  GET  /api/observations/{id}  the live decision trail
  GET  /api/download/{id}      the completed 1040 PDF
"""

from __future__ import annotations

import os
import uuid

from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, model_validator

# Load .env before importing modules that read env at import time (e.g. VISION_MODEL
# in w2_extract) and before any request reads ANTHROPIC_API_KEY for Claude vision.
# A no-op if python-dotenv isn't installed or no .env exists.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ModuleNotFoundError:
    pass

from .conversation import TaxSession

HERE = os.path.dirname(__file__)
STATIC = os.path.join(HERE, "..", "static")
ASSETS = os.path.join(HERE, "..", "assets")
# `or` (not a default arg) so an empty OUTPUT_DIR= in .env falls back rather than
# becoming "" and breaking makedirs.
OUTPUT_DIR = os.environ.get("OUTPUT_DIR") or os.path.join(HERE, "..", "_outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="Agentic Tax-Filing Assistant", version="3.0.0")
_SESSIONS: dict[str, TaxSession] = {}


def _get(session_id: str) -> TaxSession:
    s = _SESSIONS.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    return s


class MessageIn(BaseModel):
    # `session_id` is optional: a missing/unknown one auto-starts a session.
    # `text` is accepted as an alias for `message` — both name the user's turn.
    session_id: Optional[str] = None
    message: Optional[str] = None
    text: Optional[str] = None

    @model_validator(mode="after")
    def _coalesce_message(self) -> "MessageIn":
        self.message = (self.message or self.text or "").strip()
        return self


class SidIn(BaseModel):
    session_id: str


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


@app.get("/healthz")
def health():
    return {"ok": True, "sessions": len(_SESSIONS)}


def _start_session() -> tuple[str, TaxSession]:
    sid = uuid.uuid4().hex[:12]
    s = TaxSession(sid, OUTPUT_DIR)
    _SESSIONS[sid] = s
    return sid, s


@app.post("/api/session")
def new_session():
    sid, s = _start_session()
    snap = s.begin()
    snap["session_id"] = sid
    return JSONResponse(snap)


@app.post("/api/message")
def message(body: MessageIn):
    sid = body.session_id
    s = _SESSIONS.get(sid) if sid else None
    if s is None:  # missing or unknown session — start a fresh one transparently
        sid, s = _start_session()
        s.begin()  # seed the scope-lock observation, discard the greeting snapshot
    snap = s.message(body.message)
    snap["session_id"] = sid  # echo it back so the caller can keep using it
    return JSONResponse(snap)


@app.post("/api/w2")
async def upload_w2(
    session_id: str = Form(...),
    text: str = Form(default=""),
    file: UploadFile | None = File(default=None),
):
    s = _get(session_id)
    if file is not None:
        content = await file.read()
        media = file.content_type or "image/png"
        return JSONResponse(s.ingest_w2(image_bytes=content, media_type=media))
    if text.strip():
        return JSONResponse(s.ingest_w2(text=text))
    raise HTTPException(status_code=400, detail="Provide a W-2 file or figures.")


@app.post("/api/sample")
def sample(body: SidIn):
    """Load the bundled fake W-2 — a convenience for judges with no W-2 handy."""
    return JSONResponse(_get(body.session_id).load_sample())


@app.get("/api/sample-w2")
def sample_w2():
    path = os.path.join(ASSETS, "sample_w2.png")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No sample available.")
    return FileResponse(path, media_type="image/png", filename="sample_w2.png")


@app.get("/api/observations/{session_id}")
def observations(session_id: str):
    s = _get(session_id)
    return {"observations": s.obs.trail(), "obs_count": s.obs.trail_count}


@app.get("/api/download/{session_id}")
def download(session_id: str):
    s = _get(session_id)
    if not s.pdf_path or not os.path.exists(s.pdf_path):
        raise HTTPException(status_code=404, detail="No completed form yet.")
    return FileResponse(s.pdf_path, media_type="application/pdf",
                        filename="Form_1040_2025_completed.pdf")


@app.post("/api/reset")
def reset(body: SidIn):
    _get(body.session_id).reset()
    return {"ok": True}
