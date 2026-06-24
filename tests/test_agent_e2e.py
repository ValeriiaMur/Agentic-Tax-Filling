"""End-to-end harness test: sample W-2 in -> downloadable 1040 out, no LLM key.

Exercises the real free-text TaxSession + LangGraph compute pipeline + tool
registry + PDF fill together, proving the system works happy-path end to end.
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
    s.load_sample()                 # backend fixture (no LLM needed)
    s.message("yes")                # confirm figures
    s.message("single")             # filing status
    snap = s.message("no dependents")  # dependents -> compute + fill

    assert snap["phase"] == "complete"
    assert snap["pdf_ready"] is True
    assert snap["result"]["outcomeAmount"] == "$1,285"
    assert s.budget.asked <= 5

    # the produced PDF carries the computed values (tools ran via LangGraph)
    fields = PdfReader(s.pdf_path).get_fields()
    assert fields[FIELD_MAP["line_16_tax"]].get("/V") == "2,915"
    assert fields[FIELD_MAP["line_35a_refund"]].get("/V") == "1,285"

    # the observation trail recorded the tool calls and the phased decisions
    labels = [e["label"] for e in s.obs.as_list()]
    assert any("compute_1040" in l for l in labels)
    assert any("fill_1040_pdf" in l for l in labels)
    phases = {o["phase"] for o in s.obs.trail()}
    assert {"Session", "Vision", "Reasoning", "Calculation", "Decision"} <= phases


def test_out_of_scope_is_declined():
    s = TaxSession("e2e2", tempfile.mkdtemp())
    s.begin(); s.load_sample()
    snap = s.message("what stocks should I buy?")
    assert "outside" in snap["assistant_message"].lower()
    assert snap["questions_asked"] == 1  # only the confirm question so far
