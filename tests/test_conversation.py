"""TDD spec for the design-aligned TaxSession flow.

Pins the stage machine, the 5-question budget, guardrail logging, and that all
tax figures come from the backend — driven exactly as the UI drives it.
"""

import os
import tempfile

import pytest

from app.conversation import QUESTIONS, Stage, TaxSession, build_questions

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "f1040_2025.pdf")
pytestmark = pytest.mark.skipif(not os.path.exists(ASSET), reason="1040 template missing")


def _session():
    return TaxSession("t", tempfile.mkdtemp())


def test_questions_sourced_from_backend_constants():
    qs = build_questions()
    assert len(qs) == 5
    # the standard-deduction figures come from the 2025 tables, not the frontend
    single = next(o for o in qs[0]["options"] if o["value"] == "single")
    assert "$15,750" in single["sub"]


def test_begin_moves_to_upload():
    s = _session()
    out = s.begin()
    assert out["stage"] == "upload"
    assert s.stage == Stage.UPLOAD
    assert out["obs_count"] >= 1  # Session observation logged


def test_clean_path_full_flow_refund():
    s = _session()
    s.begin()
    up = s.upload(False)
    assert up["stage"] == "confirm"
    assert up["w2"]["rows"][0]["flagged"] is False
    c = s.confirm()
    assert c["stage"] == "questions" and c["question"]["id"] == "filing_status"
    s.answer("single"); s.answer(0); s.answer("no"); s.answer("standard")
    fin = s.answer(0)
    assert fin["stage"] == "review"
    assert fin["result"]["outcomeLabel"] == "Your refund"
    assert fin["result"]["outcomeAmount"] == "$1,285"
    assert s.budget.asked == 5
    assert s.pdf_path and os.path.exists(s.pdf_path)


def test_messy_path_flags_box1_and_logs_guardrail():
    s = _session()
    s.begin()
    up = s.upload(True)
    assert up["w2"]["confLabel"] == "needs review"
    assert up["w2"]["rows"][0]["flagged"] is True
    assert any(o["flag"] for o in up["observations"])  # Box 1 flagged guardrail


def test_dependents_apply_child_tax_credit():
    s = _session()
    s.begin(); s.upload(False); s.confirm()
    s.answer("single"); s.answer(2); s.answer("no"); s.answer("standard")
    fin = s.answer(0)
    lines = {l["line"]: l["value"] for l in fin["result"]["lines"]}
    assert "19" in lines  # CTC line present
    # CTC capped at the tax (2,915) for 2 deps -> tax after credits 0
    assert lines["22"] == "$0"


def test_itemized_and_other_income_log_guardrails():
    s = _session()
    s.begin(); s.upload(False); s.confirm()
    s.answer("single"); s.answer(0); s.answer("yes"); s.answer("itemized")
    fin = s.answer(0)
    flagged = [o["action"] for o in fin["observations"] if o["flag"]]
    assert "Out-of-scope income" in flagged
    assert "Deduction method" in flagged


def test_budget_never_exceeds_five():
    s = _session()
    s.begin(); s.upload(False); s.confirm()
    for v in ["single", 0, "no", "standard", 0]:
        s.answer(v)
    assert s.budget.asked == 5


def test_command_off_topic_declines_and_logs():
    s = _session()
    s.begin(); s.upload(False); s.confirm()
    s.answer("single"); s.answer(0); s.answer("no"); s.answer("standard"); s.answer(0)
    out = s.command("what stocks should I buy?")
    assert out["toast"]
    assert any(o["action"] == "Out-of-scope request" for o in out["observations"])


def test_command_on_topic_answers_from_result():
    s = _session()
    s.begin(); s.upload(False); s.confirm()
    s.answer("single"); s.answer(0); s.answer("no"); s.answer("standard"); s.answer(0)
    out = s.command("what's my refund?")
    assert "$1,285" in out["agent"]["text"]
