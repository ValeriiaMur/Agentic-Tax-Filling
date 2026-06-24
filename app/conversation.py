"""Deterministic conversation policy — the agent's decision core.

This module owns *what* the agent does each turn and enforces the guardrails in
code. The LangGraph agent wraps it to add warm phrasing (via Claude) and emits
observation events. Keeping the policy here, separate and deterministic, is what
makes the harness legible and testable: the 5-question budget, status parsing,
and W-2 confirmation are enforced regardless of the LLM.

Conversation design (≤5 questions):
  Q1  Confirm the W-2 figures I read.
  Q2  What's your filing status?
  Q3  Any dependents?
  (identity comes from the W-2; we generate after Q3)

That's three questions for the core flow, leaving headroom under the budget for
a clarification if the user's answer is ambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .guardrails import QuestionBudget, classify_scope, parse_filing_status
from .schemas import Form1040Result, TaxpayerInfo, W2
from .tax_engine import compute_1040


class Phase(str, Enum):
    AWAIT_W2 = "await_w2"
    CONFIRM_W2 = "confirm_w2"
    FILING_STATUS = "filing_status"
    DEPENDENTS = "dependents"
    COMPLETE = "complete"


@dataclass
class TurnResult:
    message: str
    declined: bool = False
    asked_question: bool = False
    events: List[tuple] = field(default_factory=list)


class SessionState:
    """All conversation state for one user session. Held across turns."""

    def __init__(self) -> None:
        self.phase: Phase = Phase.AWAIT_W2
        self.w2: dict = {}
        self.info: dict = {"filing_status": None, "num_dependents": 0}
        self.budget = QuestionBudget(limit=5)
        self.result: Optional[Form1040Result] = None
        self.pdf_path: Optional[str] = None
        self.history: List[dict] = []

    @property
    def questions_asked(self) -> int:
        return self.budget.asked

    def apply_w2(self, payload: dict) -> None:
        self.w2 = dict(payload)
        # carry the name through if present
        if payload.get("employee_name") and not self.info.get("first_last"):
            parts = str(payload["employee_name"]).split()
            if parts:
                self.info["first_name"] = parts[0]
                self.info["last_name"] = " ".join(parts[1:]) if len(parts) > 1 else ""
        self.phase = Phase.CONFIRM_W2

    def build_taxpayer(self) -> TaxpayerInfo:
        return TaxpayerInfo(
            filing_status=self.info.get("filing_status") or "single",
            first_name=self.info.get("first_name", ""),
            last_name=self.info.get("last_name", ""),
            ssn=self.w2.get("employee_ssn", ""),
            num_dependents=int(self.info.get("num_dependents", 0) or 0),
        )

    def compute(self) -> Form1040Result:
        w2 = W2(
            box1_wages=float(self.w2.get("box1_wages") or 0),
            box2_federal_withholding=float(self.w2.get("box2_federal_withholding") or 0),
            employee_name=self.w2.get("employee_name", ""),
        )
        self.result = compute_1040(w2, self.build_taxpayer())
        return self.result


_YES = ("yes", "yep", "yeah", "correct", "right", "looks good", "that's right",
        "sure", "ok", "okay", "confirm", "good")


def _looks_affirmative(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in _YES)


def advance(state: SessionState, user_message: str) -> TurnResult:
    """Advance the conversation by one user turn. Pure policy, no LLM."""
    events: List[tuple] = []

    # Scope guardrail applies in every phase and never costs a question.
    if classify_scope(user_message) == "out_of_scope":
        events.append(("guardrail", "out_of_scope_declined", {"text": user_message[:80]}))
        return TurnResult(
            message=(
                "I'm here just to help you fill out your 2025 Form 1040 from your "
                "W-2 — I can't weigh in on investing or give tax advice. Want to "
                "keep going with your return?"
            ),
            declined=True,
            events=events,
        )

    if state.phase == Phase.AWAIT_W2:
        return TurnResult(
            message=(
                "Happy to help you get your 2025 federal return done. To start, "
                "share your W-2 — you can upload a photo or PDF, or just type in "
                "your Box 1 wages and Box 2 federal withholding."
            ),
            events=events,
        )

    if state.phase == Phase.CONFIRM_W2:
        if _looks_affirmative(user_message):
            state.phase = Phase.FILING_STATUS
            if state.budget.can_ask():
                state.budget.record_question()
            events.append(("decision", "w2_confirmed", {}))
            return TurnResult(
                message=(
                    "Great, thank you. One quick thing so I use the right "
                    "standard deduction: what's your filing status — single, "
                    "married filing jointly, married filing separately, or head "
                    "of household?"
                ),
                asked_question=True,
                events=events,
            )
        # not a clear yes: re-ask to confirm (counts as a question, budget-guarded)
        if state.budget.can_ask():
            state.budget.record_question()
        w = state.w2
        return TurnResult(
            message=(
                f"Let me make sure I've got your W-2 right: Box 1 wages of "
                f"${float(w.get('box1_wages') or 0):,.0f} and Box 2 federal "
                f"withholding of ${float(w.get('box2_federal_withholding') or 0):,.0f}. "
                "Is that correct? If a number's off, just tell me the right one."
            ),
            asked_question=True,
            events=events,
        )

    if state.phase == Phase.FILING_STATUS:
        status = parse_filing_status(user_message)
        if status is None:
            if state.budget.can_ask():
                state.budget.record_question()
            return TurnResult(
                message=(
                    "No worries — just let me know which fits best: single, "
                    "married filing jointly, married filing separately, or head "
                    "of household?"
                ),
                asked_question=True,
                events=events,
            )
        state.info["filing_status"] = status
        state.phase = Phase.DEPENDENTS
        if state.budget.can_ask():
            state.budget.record_question()
        events.append(("decision", "filing_status_set", {"status": status}))
        return TurnResult(
            message=(
                "Got it. Last question: do you have any dependents you're "
                "claiming this year? If so, how many?"
            ),
            asked_question=True,
            events=events,
        )

    if state.phase == Phase.DEPENDENTS:
        num = _parse_dependents(user_message)
        state.info["num_dependents"] = num
        events.append(("decision", "dependents_set", {"num": num}))
        result = state.compute()
        events.append(("tool_result", "compute_1040", {
            "taxable_income": result.line_15_taxable_income,
            "tax": result.line_16_tax,
            "refund": result.line_35a_refund,
            "amount_owed": result.line_37_amount_owed,
        }))
        state.phase = Phase.COMPLETE
        outcome = (
            f"a refund of ${result.line_35a_refund:,}"
            if result.line_35a_refund > 0
            else f"a balance due of ${result.line_37_amount_owed:,}"
        )
        return TurnResult(
            message=(
                f"All set — I've filled out your 2025 Form 1040. With "
                f"${result.line_1a_wages:,} in wages and the "
                f"${result.line_12_standard_deduction:,} standard deduction, your "
                f"taxable income is ${result.line_15_taxable_income:,} and your tax "
                f"is ${result.line_16_tax:,}. You're getting {outcome}. "
                "You can download the completed form now."
            ),
            events=events,
        )

    # COMPLETE: allow re-download or status change
    new_status = parse_filing_status(user_message)
    if new_status and new_status != state.info.get("filing_status"):
        state.info["filing_status"] = new_status
        state.compute()
        events.append(("decision", "recomputed_status_change", {"status": new_status}))
        return TurnResult(
            message=(
                f"Updated to {new_status.replace('_', ' ')}. Your new tax is "
                f"${state.result.line_16_tax:,}. The download reflects the change."
            ),
            events=events,
        )
    return TurnResult(
        message="Your 2025 Form 1040 is ready to download. Anything you'd like to change?",
        events=events,
    )


def _parse_dependents(text: str) -> int:
    low = text.lower()
    if any(w in low for w in ("no", "none", "zero", "nope", "0")):
        return 0
    import re
    m = re.search(r"\d+", low)
    if m:
        return min(4, int(m.group(0)))
    return 0
