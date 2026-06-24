"""End-to-end harness test: fake W-2 in -> downloadable 1040 out, no LLM key.

Exercises the real LangGraph agent, tool registry, guardrails, and PDF fill
together, proving the system works happy-path end to end offline.
"""

import os

import pytest
from pypdf import PdfReader

from app.agent import TaxAgent
from app.pdf_fill import FIELD_MAP

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "f1040_2025.pdf")
pytestmark = pytest.mark.skipif(not os.path.exists(ASSET), reason="1040 template missing")


def test_full_session_produces_correct_1040(tmp_path):
    agent = TaxAgent("testsession", str(tmp_path))

    # 1) W-2 supplied as pasted text (vision fallback path)
    r = agent.ingest_w2(text="Box 1 wages 42,000  Box 2 federal withholding 4,200  Employee: Jordan Rivera")
    assert agent.state.phase.value == "confirm_w2"

    # 2) confirm figures
    agent.handle_message("yes that's correct")
    # 3) filing status
    agent.handle_message("single")
    # 4) dependents -> triggers compute + finalize (pdf)
    out = agent.handle_message("no dependents")

    assert out["pdf_ready"] is True
    assert out["questions_asked"] <= 5
    assert out["result"]["line_16_tax"] == 2915
    assert out["result"]["line_35a_refund"] == 1285

    # the produced PDF carries the computed values
    reader = PdfReader(agent.pdf_path)
    fields = reader.get_fields()
    assert fields[FIELD_MAP["line_16_tax"]].get("/V") == "2,915"
    assert fields[FIELD_MAP["line_35a_refund"]].get("/V") == "1,285"

    # observation trail recorded the tool calls
    kinds = [e["kind"] for e in out["events"]]
    labels = [e["label"] for e in out["events"]]
    assert "tool_call" in kinds and "tool_result" in kinds
    assert "compute_1040" in labels and "fill_1040_pdf" in labels


def test_out_of_scope_is_declined(tmp_path):
    agent = TaxAgent("s2", str(tmp_path))
    agent.ingest_w2(text="Box 1 wages 42000 Box 2 4200")
    out = agent.handle_message("should I invest in a roth ira?")
    assert out["assistant_message"]
    # budget not spent on an off-task message
    assert out["questions_asked"] == 0
