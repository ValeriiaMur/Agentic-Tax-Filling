"""TDD spec for the deterministic conversation policy.

The policy decides what happens each turn and enforces the guardrails in code:
the 5-question budget, filing-status parsing, and W-2 confirmation. The LLM only
rephrases the policy's intent warmly; it never controls the flow, so these tests
pin the agent's actual behavior.
"""

from app.conversation import Phase, SessionState, advance


def _seed_with_w2():
    st = SessionState()
    # simulate a successful W-2 ingest
    st.apply_w2({"box1_wages": 42000, "box2_federal_withholding": 4200,
                 "employee_name": "Jordan Rivera"})
    return st


def test_starts_by_requesting_w2():
    st = SessionState()
    assert st.phase == Phase.AWAIT_W2
    out = advance(st, "hi")
    assert st.phase == Phase.AWAIT_W2
    assert "w-2" in out.message.lower() or "w2" in out.message.lower()


def test_w2_ingest_moves_to_confirm():
    st = _seed_with_w2()
    assert st.phase == Phase.CONFIRM_W2
    assert st.w2["box1_wages"] == 42000


def test_full_happy_path_within_budget():
    st = _seed_with_w2()
    # confirm W-2 figures
    out = advance(st, "yes that's right")
    assert st.phase == Phase.FILING_STATUS
    # filing status
    out = advance(st, "I'm single")
    assert st.info["filing_status"] == "single"
    # dependents
    out = advance(st, "no dependents")
    # now we should be ready/complete with a computed result
    assert st.result is not None
    assert st.result.line_16_tax == 2915
    assert st.questions_asked <= 5


def test_budget_never_exceeds_five():
    st = _seed_with_w2()
    for msg in ["yes", "single", "none", "what", "huh", "ok", "sure"]:
        advance(st, msg)
    assert st.questions_asked <= 5


def test_filing_status_change_recomputes():
    st = _seed_with_w2()
    advance(st, "correct")
    advance(st, "married filing jointly")
    advance(st, "no dependents")
    assert st.info["filing_status"] == "married_filing_jointly"
    assert st.result.line_12_standard_deduction == 31500


def test_out_of_scope_is_declined_without_spending_budget():
    st = _seed_with_w2()
    before = st.questions_asked
    out = advance(st, "should I invest in a roth ira instead?")
    assert out.declined is True
    # declining must not consume a question or derail the phase
    assert st.questions_asked == before
