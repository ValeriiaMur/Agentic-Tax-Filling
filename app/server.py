"""FastAPI app for the Malleable-UI tax assistant.

Drives the design's stage machine via discrete endpoints. All data — W-2 figures,
the five questions, the computed return, and the decision trail — is produced
here on the server; the browser holds none of it hardcoded.
"""

from __future__ import annotations

import os
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from .conversation import QUESTIONS, TaxSession

HERE = os.path.dirname(__file__)
STATIC = os.path.join(HERE, "..", "static")
ASSETS = os.path.join(HERE, "..", "assets")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(HERE, "..", "_outputs"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="Agentic Tax-Filing Assistant", version="2.0.0")
_SESSIONS: dict[str, TaxSession] = {}


def _get(session_id: str) -> TaxSession:
    s = _SESSIONS.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    return s


class SidIn(BaseModel):
    session_id: str


class UploadIn(SidIn):
    messy: bool = False


class ConfirmIn(SidIn):
    box1_override: float | None = None


class AnswerIn(SidIn):
    value: object


class CommandIn(SidIn):
    text: str


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
    _SESSIONS[sid] = TaxSession(sid, OUTPUT_DIR)
    return {"session_id": sid}


@app.get("/api/questions")
def questions():
    """The five questions, with all tax figures sourced from the backend."""
    return {"questions": QUESTIONS}


@app.post("/api/begin")
def begin(body: SidIn):
    return JSONResponse(_get(body.session_id).begin())


@app.post("/api/upload")
async def upload(
    session_id: str = Form(...),
    messy: bool = Form(default=False),
    file: UploadFile | None = File(default=None),
):
    s = _get(session_id)
    if file is not None:
        content = await file.read()
        return JSONResponse(s.upload(bool(messy), image_bytes=content,
                                     media_type=file.content_type or "image/png"))
    return JSONResponse(s.upload(bool(messy)))


@app.post("/api/upload-json")
def upload_json(body: UploadIn):
    """Sample/messy demo buttons (no file) — figures come from the backend fixture."""
    return JSONResponse(_get(body.session_id).upload(bool(body.messy)))


@app.post("/api/confirm")
def confirm(body: ConfirmIn):
    return JSONResponse(_get(body.session_id).confirm(box1_override=body.box1_override))


@app.post("/api/answer")
def answer(body: AnswerIn):
    return JSONResponse(_get(body.session_id).answer(body.value))


@app.post("/api/finalize")
def finalize(body: SidIn):
    return JSONResponse(_get(body.session_id).finalize())


@app.post("/api/command")
def command(body: CommandIn):
    return JSONResponse(_get(body.session_id).command(body.text))


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
                        filename="Form_1040_2025.pdf")


@app.post("/api/reset")
def reset(body: SidIn):
    _get(body.session_id).reset()
    return {"ok": True}
