"""End-to-end harness test: sample W-2 in -> downloadable 1040 out, no LLM key.

Exercises the real TaxSession + LangGraph compute pipeline + tool registry +
PDF fill together, proving the system works happy-path end to end offline.
"""

import os
import tempfile

import pytest
from pypdf import PdfReader

from app.conversation import TaxSession
from app.pdf_fill import FIELD_MAP

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "f1040_2025.pdf")
pytestmark = pytest.mark.skipif(not os.path.exists(ASSET), reason="1040 template missing")


def test_full_session_produces_correct_1040():
    s = TaxSession("e2e", tempfile.mkdtemp())
    s.begin()
    s.upload(False)            # sample fixture (vision fallback)
    s.confirm()
    s.answer("single"); s.answer(0); s.answer("no"); s.answer("standard")
    fin = s.answer(0)

    assert fin["stage"] == "review"
    assert fin["result"]["outcomeAmount"] == "$1,285"
    assert s.budget.asked <= 5

    # the produced PDF carries the computed values (tools ran via LangGraph)
    reader = PdfReader(s.pdf_path)
    fields = reader.get_fields()
    assert fields[FIELD_MAP["line_16_tax"]].get("/V") == "2,915"
    assert fields[FIELD_MAP["line_35a_refund"]].get("/V") == "1,285"

    # observation trail recorded the tool calls + computation
    labels = [e["label"] for e in s.obs.as_list()]
    assert any("compute_1040" in l for l in labels)
    assert any("fill_1040_pdf" in l for l in labels)
    # decision trail has phased entries
    phases = {o["phase"] for o in s.obs.trail()}
    assert {"Session", "Vision", "Reasoning", "Calculation", "Decision"} <= phases


def test_finalize_then_download_ready():
    s = TaxSession("e2e2", tempfile.mkdtemp())
    s.begin(); s.upload(False); s.confirm()
    s.answer("single"); s.answer(0); s.answer("no"); s.answer("standard"); s.answer(0)
    out = s.finalize()
    assert out["stage"] == "download"
    assert os.path.exists(s.pdf_path)
