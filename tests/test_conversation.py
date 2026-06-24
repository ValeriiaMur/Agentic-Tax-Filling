"""TDD spec for the free-text TaxSession flow.

Pins the conversational stage machine, the 5-question budget, deterministic
intent parsing, guardrails, and that the figures come from the backend.
"""

import os
import tempfile

import pytest

from app.conversation import Phase, TaxSession

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "f1040_2025.pdf")
pytestmark = pytest.mark.skipif(not os.path.exists(ASSET), reason="1040 template missing")


def _session():
    return TaxSession("t", tempfile.mkdtemp())


def test_begin_greets_and_awaits_w2():
    s = _session()
    snap = s.begin()
    assert s.phase == Phase.AWAIT_W2
    assert "Form 1040" in snap["assistant_message"]
    assert snap["obs_count"] >= 1  # Session observation


def test_sample_moves_to_confirm():
    s = _session()
    s.begin()
    snap = s.load_sample()
    assert snap["phase"] == "confirm_w2"
    assert "42,000" in snap["assistant_message"]  # backend figure, echoed back


def test_paste_figures_ingests_w2():
    s = _session()
    s.begin()
    snap = s.message("Box 1 wages 42000, Box 2 withholding 4200")
    assert snap["phase"] == "confirm_w2"


def test_sample_w2_fills_full_1040_header():
    from pypdf import PdfReader
    from app.pdf_fill import FIELD_MAP
    s = _session()
    s.begin(); s.load_sample()
    s.message("yes"); s.message("single"); s.message("no dependents")
    f = PdfReader(s.pdf_path).get_fields()
    assert f[FIELD_MAP["first_name"]].get("/V") == "Jordan A"
    assert f[FIELD_MAP["last_name"]].get("/V") == "Rivera"
    assert f[FIELD_MAP["ssn"]].get("/V") == "123-45-6789"
    assert f[FIELD_MAP["address"]].get("/V") == "100 Main St"
    assert f[FIELD_MAP["city"]].get("/V") == "Austin"
    assert f[FIELD_MAP["state"]].get("/V") == "TX"
    assert f[FIELD_MAP["zip"]].get("/V") == "78701"


def test_full_happy_path_refund_within_budget():
    s = _session()
    s.begin(); s.load_sample()
    s.message("yes that's right")          # confirm
    s.message("single")                    # filing status
    snap = s.message("no dependents")      # dependents -> compute
    assert snap["phase"] == "complete"
    assert snap["pdf_ready"] is True
    assert snap["result"]["outcomeAmount"] == "$1,285"
    assert s.budget.asked <= 5
    assert os.path.exists(s.pdf_path)


def test_typed_figures_asks_identity_and_fills_header():
    from pypdf import PdfReader
    from app.pdf_fill import FIELD_MAP
    s = _session()
    s.begin()
    s.message("Box 1 wages 42000, Box 2 withholding 4200")  # no name on this path
    s.message("yes"); s.message("single")
    d = s.message("no dependents")
    assert d["phase"] == "identity"  # asks for name/address since W-2 had none
    fin = s.message("Jordan Rivera, 100 Main St, Austin, TX 78701")
    assert fin["phase"] == "complete"
    assert s.budget.asked <= 5
    f = PdfReader(s.pdf_path).get_fields()
    assert f[FIELD_MAP["last_name"]].get("/V") == "Rivera"
    assert f[FIELD_MAP["city"]].get("/V") == "Austin"


def test_sample_path_skips_identity_question():
    s = _session()
    s.begin(); s.load_sample()
    s.message("yes"); s.message("single")
    d = s.message("no dependents")
    assert d["phase"] == "complete"   # identity came from the W-2, no extra question
    assert s.budget.asked == 3


def test_filing_status_changes_deduction():
    s = _session()
    s.begin(); s.load_sample()
    s.message("correct")
    s.message("married filing jointly")
    snap = s.message("none")
    lines = {l["line"]: l["value"] for l in snap["result"]["lines"]}
    assert lines["12"] == "$31,500"        # MFJ standard deduction


def test_w2_correction_during_confirm():
    s = _session()
    s.begin(); s.load_sample()
    snap = s.message("no, box 1 is 50000")
    assert "50,000" in snap["assistant_message"]
    assert s.w2["box1_wages"] == 50000


def test_confirm_phase_accepts_jump_to_filing_status():
    # If the user skips the yes/no and answers the next question outright
    # ("single"), accept the W-2 as read and advance — don't nag for a
    # confirmation we don't actually need.
    s = _session()
    s.begin(); s.load_sample()
    snap = s.message("single")
    assert s.phase == Phase.DEPENDENTS
    assert s.info["filing_status"] == "single"
    assert "42,000" in snap["assistant_message"] or "dependent" in snap["assistant_message"].lower()


def test_dependents_apply_child_tax_credit():
    s = _session()
    s.begin(); s.load_sample()
    s.message("yes"); s.message("single")
    snap = s.message("2 kids")
    lines = {l["line"]: l["value"] for l in snap["result"]["lines"]}
    assert "19" in lines                   # CTC line present


def test_out_of_scope_declined_without_burning_a_question():
    s = _session()
    s.begin(); s.load_sample()
    before = s.budget.asked
    snap = s.message("should I invest in a roth ira instead?")
    assert s.budget.asked == before
    assert any(o["action"] == "Out-of-scope request" for o in snap["observations"])


def test_mid_conversation_status_change_recomputes():
    s = _session()
    s.begin(); s.load_sample()
    s.message("yes"); s.message("single"); s.message("no")
    snap = s.message("actually head of household")
    lines = {l["line"]: l["value"] for l in snap["result"]["lines"]}
    assert lines["12"] == "$23,625"        # HoH deduction after recompute


def test_budget_never_exceeds_five():
    s = _session()
    s.begin(); s.load_sample()
    for m in ["huh", "what", "no", "maybe", "single", "none", "ok"]:
        s.message(m)
    assert s.budget.asked <= 5
