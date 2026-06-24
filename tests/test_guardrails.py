"""TDD spec for the guardrails layer (written before the implementation)."""

import pytest

from app.guardrails import (
    QuestionBudget,
    classify_scope,
    parse_filing_status,
    validate_w2_payload,
)


# --- Question budget: hard cap of 5, enforced in code (not the prompt) ------

def test_budget_allows_up_to_five_questions():
    b = QuestionBudget(limit=5)
    for _ in range(5):
        assert b.can_ask() is True
        b.record_question()
    assert b.can_ask() is False
    assert b.asked == 5


def test_budget_remaining_counts_down():
    b = QuestionBudget(limit=5)
    b.record_question()
    b.record_question()
    assert b.remaining == 3


# --- Scope guardrail: keep the agent on-task -------------------------------

@pytest.mark.parametrize("text", [
    "should I invest in Roth IRA vs index funds?",
    "what stocks should I buy",
    "can you give me tax advice on my rental property depreciation",
])
def test_out_of_scope_detected(text):
    assert classify_scope(text) == "out_of_scope"


@pytest.mark.parametrize("text", [
    "I'm single",
    "my wages were 42000",
    "here is my w-2",
    "I have no dependents",
])
def test_on_task_allowed(text):
    assert classify_scope(text) == "on_task"


# --- Filing-status parsing: robust, deterministic --------------------------

@pytest.mark.parametrize("text,expected", [
    ("single", "single"),
    ("I'm not married", "single"),
    ("married filing jointly", "married_filing_jointly"),
    ("we file together", "married_filing_jointly"),
    ("married filing separately", "married_filing_separately"),
    ("head of household", "head_of_household"),
])
def test_parse_filing_status(text, expected):
    assert parse_filing_status(text) == expected


def test_parse_filing_status_unknown_returns_none():
    assert parse_filing_status("purple monkey dishwasher") is None


# --- W-2 validation guardrail ----------------------------------------------

def test_validate_good_w2():
    ok, issues = validate_w2_payload({"box1_wages": 42000, "box2_federal_withholding": 4200})
    assert ok is True
    assert issues == []


def test_validate_flags_withholding_above_wages():
    ok, issues = validate_w2_payload({"box1_wages": 1000, "box2_federal_withholding": 5000})
    assert ok is False
    assert any("withholding" in i.lower() for i in issues)


def test_validate_requires_wages():
    ok, issues = validate_w2_payload({"box2_federal_withholding": 100})
    assert ok is False
    assert any("wages" in i.lower() for i in issues)
