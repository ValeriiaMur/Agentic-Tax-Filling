"""Free-text conversation policy — the agent's decision core.

The brief is explicit: the conversation must feel "warm and human — friendly,
clear, not robotic or interrogative," and gather what it needs in **no more than
five questions**. So this is a natural free-text chat, not a click-through of
multiple-choice buttons. The user types; the agent reads intent in code.

Why the policy lives here (and is deterministic):
  * Chat loop   - `TaxSession` carries phase, W-2, answers, the question budget,
                  and the result across turns. One `message(text)` call = one turn.
  * Tools       - extraction, computation, and PDF fill run through `ToolRegistry`
                  and the LangGraph compute pipeline (see agent.py).
  * Guardrails  - a hard 5-question budget, out-of-scope decline, deterministic
                  filing-status parsing, and W-2 validation — all enforced in code,
                  not "asked for" in a prompt.
  * Observation - every decision, tool call, and computed line value is appended
                  to the session's ObservationLog and surfaced in the UI trail.

Conversation design (≤5 questions, with headroom):
  Q1  Confirm the W-2 figures I read.   (human-in-the-loop check)
  Q2  What's your filing status?
  Q3  Any dependents?
  (identity comes from the W-2; we compute after Q3.)

That is three core questions, leaving two in reserve for a clarification or a
mid-conversation correction. When the budget is exhausted the agent degrades
gracefully — it assumes a safe default and says so — rather than looping.
"""

from __future__ import annotations

import json
import os
import re
from enum import Enum
from typing import Optional

from . import tax_tables_2025 as T
from .guardrails import (
    QuestionBudget,
    classify_scope,
    parse_filing_status,
    validate_w2_payload,
)
from .observability import ObservationLog
from .schemas import Form1040Result, TaxpayerInfo, W2
from .tools import ToolRegistry
from .w2_extract import _NUM, _to_float, parse_w2_text

HERE = os.path.dirname(__file__)
SAMPLE_W2_JSON = os.path.join(HERE, "..", "assets", "sample_w2.json")


class Phase(str, Enum):
    AWAIT_W2 = "await_w2"
    CONFIRM_W2 = "confirm_w2"
    FILING_STATUS = "filing_status"
    DEPENDENTS = "dependents"
    COMPLETE = "complete"


GREETING = (
    "Hi! I'm here to help you put together your 2025 federal tax return "
    "(Form 1040) from your W-2. It only takes a minute and a couple of quick "
    "questions.\n\nTo start, you can upload a photo or PDF of your W-2 — or just "
    "type in your Box 1 wages and Box 2 federal withholding and I'll take it from "
    "there.\n\n(This is an educational demo with fake data — not tax advice or a "
    "real filing.)"
)


def _money(n: float) -> str:
    return "$" + f"{round(n):,}"


# ── free-text intent helpers (deterministic, negation-aware) ────────────────

_AFFIRM = ("yes", "yep", "yeah", "yup", "correct", "right", "looks good",
           "looks right", "all good", "perfect", "exactly", "confirm",
           "confirmed", "that's it", "thats it", "good", "sure", "ok", "okay",
           "sounds good", "great")

# A negation anywhere flips an otherwise-affirmative reading ("no, that's not
# correct" contains "correct" but is clearly a NO).
_NEGATE = (r"\bno\b", r"\bnope\b", r"\bnot\b", r"n't\b", r"\bwrong\b",
           r"\bincorrect\b", r"\boff\b", r"\bnah\b", r"\bchange\b", r"\bfix\b",
           r"\bedit\b", r"\bactually\b", r"\bshould be\b")


def _has_negation(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in _NEGATE)


def _is_affirmative(text: str) -> bool:
    if _has_negation(text):
        return False
    low = text.lower()
    return any(a in low for a in _AFFIRM)


def _extract_w2_corrections(text: str) -> dict:
    """Pull explicitly-stated Box 1 / Box 2 figures from a correction message.

    Only returns keys the user actually named, so "no, box 1 is 50000" updates
    wages without silently zeroing withholding.
    """
    low = text.lower()
    out: dict = {}
    m = (re.search(r"box\s*1[^0-9$]*" + _NUM, low)
         or re.search(r"wages?[^0-9$]*" + _NUM, low))
    if m:
        out["box1_wages"] = _to_float(m.group(1))
    m = (re.search(r"box\s*2[^0-9$]*" + _NUM, low)
         or re.search(r"(?:federal\s*)?(?:income\s*tax\s*)?(?:withh?olding|withheld)[^0-9$]*" + _NUM, low))
    if m:
        out["box2_federal_withholding"] = _to_float(m.group(1))
    return out


def _parse_dependents(text: str) -> tuple[int, bool]:
    """Return (num_dependents, capped). Caps at 4 for this prototype's CTC model."""
    low = text.lower()
    if re.search(r"\b(no|none|nope|zero|0)\b", low):
        return 0, False
    m = re.search(r"\d+", low)
    if m:
        n = int(m.group(0))
        return min(4, n), n > 4
    # words like "one"/"two" are uncommon in answers; default to 0 if unclear
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    for w, n in words.items():
        if re.search(rf"\b{w}\b", low):
            return min(4, n), n > 4
    return 0, False


class TaxSession:
    """All conversation state for one user session, carried across turns."""

    def __init__(self, session_id: str, output_dir: str):
        self.session_id = session_id
        self.obs = ObservationLog(session_id)
        self.tools = ToolRegistry(self.obs, output_dir)
        self.phase = Phase.AWAIT_W2
        self.w2: dict = {}
        self.info: dict = {"filing_status": None, "num_dependents": 0}
        self.budget = QuestionBudget(limit=5)
        self.result: Optional[Form1040Result] = None
        self.pdf_path: Optional[str] = None

    # ── snapshot returned to the UI each turn ──────────────────────────────
    def snapshot(self, assistant_message: str, **extra) -> dict:
        base = {
            "assistant_message": assistant_message,
            "phase": self.phase.value,
            "questions_asked": self.budget.asked,
            "questions_remaining": self.budget.remaining,
            "pdf_ready": bool(self.pdf_path),
            "observations": self.obs.trail(),
            "obs_count": self.obs.trail_count,
            "result": self.result_payload(),
        }
        base.update(extra)
        return base

    def begin(self) -> dict:
        self.obs.observe("Session", "Return started",
                         "Scope locked to U.S. federal Form 1040, tax year 2025.",
                         conf=1.0)
        return self.snapshot(GREETING)

    def _record_question(self) -> bool:
        """Count a question if the budget allows. Returns False when exhausted."""
        if self.budget.can_ask():
            self.budget.record_question()
            return True
        return False

    # ── W-2 ingestion (text paste or image/PDF via the extract_w2 tool) ─────
    def load_sample(self) -> dict:
        with open(SAMPLE_W2_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
        return self._ingest(data, source="sample")

    def ingest_w2(self, *, text: str = "", image_bytes: bytes = None,
                  media_type: str = "") -> dict:
        if image_bytes:
            data = self.tools.extract_w2(image_bytes=image_bytes, media_type=media_type)
        else:
            data = self.tools.extract_w2(text=text)
        return self._ingest(data, source="upload" if image_bytes else "text")

    def _ingest(self, data: dict, source: str) -> dict:
        ok, issues = validate_w2_payload(data)
        if data.get("box1_wages") in (None, 0) and not ok:
            # nothing usable — stay and ask again (no question burned)
            self.obs.observe("Guardrail", "W-2 not readable",
                             "Couldn't find Box 1 wages in what was provided.",
                             conf=0.4, flag=True)
            return self.snapshot(
                "I couldn't quite make out the wages there. Could you share your "
                "W-2 again — a clearer photo, or just type something like "
                "“Box 1 wages 42000, Box 2 withholding 4200”?")

        self.w2 = dict(data)
        self.phase = Phase.CONFIRM_W2
        wages = float(self.w2.get("box1_wages") or 0)
        wh = float(self.w2.get("box2_federal_withholding") or 0)
        employer = self.w2.get("employer_name") or self.w2.get("employer") or ""

        self.obs.observe("Vision", "W-2 read",
                         f"{employer + ' — ' if employer else ''}Box 1 wages "
                         f"{_money(wages)}, Box 2 withholding {_money(wh)}.",
                         conf=0.97 if source != "text" else 0.9)
        for issue in issues:
            self.obs.observe("Guardrail", "W-2 sanity check", issue, conf=0.6, flag=True)

        self._record_question()  # Q1: confirm the figures
        name = (self.w2.get("employee_name") or "").split(" ")[0]
        hello = f"Thanks{', ' + name if name else ''}! "
        return self.snapshot(
            hello + f"I read your W-2 as **{_money(wages)}** in Box 1 wages and "
            f"**{_money(wh)}** in Box 2 federal withholding. Does that look right? "
            "(If a number's off, just tell me the correct one.)")

    # ── main free-text turn handler ─────────────────────────────────────────
    def message(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return self.snapshot("Whenever you're ready — go ahead.")

        # Scope guardrail applies every turn and never costs a question.
        if classify_scope(text) == "out_of_scope":
            self.obs.observe("Guardrail", "Out-of-scope request",
                             f"“{text[:60]}” declined — I only prepare a 2025 "
                             "Form 1040 from a W-2.", conf=0.99, flag=True)
            tail = ("" if self.phase == Phase.COMPLETE
                    else " Want to keep going with your return?")
            return self.snapshot(
                "That's outside what I can help with here — I stick to preparing "
                "your 2025 Form 1040 from your W-2, and I can't give tax or "
                "investment advice." + tail)

        if self.phase == Phase.AWAIT_W2:
            return self._turn_await_w2(text)
        if self.phase == Phase.CONFIRM_W2:
            return self._turn_confirm(text)
        if self.phase == Phase.FILING_STATUS:
            return self._turn_filing_status(text)
        if self.phase == Phase.DEPENDENTS:
            return self._turn_dependents(text)
        return self._turn_complete(text)

    def _turn_await_w2(self, text: str) -> dict:
        parsed = parse_w2_text(text)
        if parsed.get("box1_wages"):
            return self.ingest_w2(text=text)
        return self.snapshot(
            "No problem — to get started I just need your W-2. You can upload a "
            "photo or PDF, or type your figures like “Box 1 wages 42000, Box 2 "
            "withholding 4200”.")

    def _turn_confirm(self, text: str) -> dict:
        corrections = _extract_w2_corrections(text)
        if corrections:
            self.w2.update(corrections)
            wages = float(self.w2.get("box1_wages") or 0)
            wh = float(self.w2.get("box2_federal_withholding") or 0)
            self.obs.observe("Reasoning", "W-2 corrected",
                             f"User updated figures → Box 1 {_money(wages)}, "
                             f"Box 2 {_money(wh)}.", conf=0.95)
            self._record_question()
            return self.snapshot(
                f"Got it — updated to **{_money(wages)}** in wages and "
                f"**{_money(wh)}** withheld. Does that look right now?")

        if _is_affirmative(text):
            self.obs.observe("Reasoning", "W-2 confirmed",
                             "Wages and withholding accepted by the taxpayer.",
                             conf=0.99)
            self.phase = Phase.FILING_STATUS
            self._record_question()  # Q2
            return self.snapshot(
                "Great, thank you. One quick thing so I use the right standard "
                "deduction: what's your filing status — single, married filing "
                "jointly, married filing separately, or head of household?")

        # A "no" with no number, or anything ambiguous: ask for the right figure.
        if not self._record_question():
            # budget exhausted — proceed with what we have rather than loop
            return self._accept_and_ask_status(
                "We're at my question limit, so I'll go with the figures I have. ")
        wages = float(self.w2.get("box1_wages") or 0)
        wh = float(self.w2.get("box2_federal_withholding") or 0)
        return self.snapshot(
            f"No worries — let's get it right. I currently have **{_money(wages)}** "
            f"in Box 1 wages and **{_money(wh)}** in Box 2 withholding. What should "
            "the correct figure be? (e.g. “Box 1 is 45000”)")

    def _accept_and_ask_status(self, prefix: str = "") -> dict:
        self.phase = Phase.FILING_STATUS
        return self.snapshot(
            prefix + "What's your filing status — single, married filing jointly, "
            "married filing separately, or head of household?")

    def _turn_filing_status(self, text: str) -> dict:
        status = parse_filing_status(text)
        if status is None:
            if self._record_question():
                return self.snapshot(
                    "No worries — which of these fits best: single, married filing "
                    "jointly, married filing separately, or head of household?")
            # exhausted: default to single, transparently
            status = T.SINGLE
            self.obs.observe("Guardrail", "Question budget reached",
                             "Couldn't confirm filing status within 5 questions — "
                             "assuming Single; the user can correct it after.",
                             conf=0.7, flag=True)

        self.info["filing_status"] = status
        self.obs.observe("Reasoning", "Filing status",
                         f"{T.FILING_STATUS_LABELS[status]} → standard deduction "
                         f"{_money(T.STANDARD_DEDUCTION[status])} (2025).", conf=0.99)
        self.phase = Phase.DEPENDENTS
        self._record_question()  # Q3
        return self.snapshot(
            "Got it. Last question: do you have any dependents you're claiming "
            "this year? If so, how many?")

    def _turn_dependents(self, text: str) -> dict:
        num, capped = _parse_dependents(text)
        self.info["num_dependents"] = num
        detail = (f"{num} dependent(s) → up to "
                  f"{_money(num * T.CHILD_TAX_CREDIT)} child tax credit.")
        if capped:
            detail += " (Capped at 4 for this prototype.)"
        self.obs.observe("Reasoning", "Dependents", detail, conf=0.97)
        return self._finalize_return()

    def _turn_complete(self, text: str) -> dict:
        # Mid-conversation correction: change filing status and recompute.
        new_status = parse_filing_status(text)
        if new_status and new_status != self.info.get("filing_status"):
            self.info["filing_status"] = new_status
            self.obs.observe("Decision", "Filing status changed",
                             f"Recomputing as {T.FILING_STATUS_LABELS[new_status]}.",
                             conf=0.98)
            return self._finalize_return(reask=False,
                prefix=f"Updated to {T.FILING_STATUS_LABELS[new_status].lower()}. ")

        corrections = _extract_w2_corrections(text)
        if corrections:
            self.w2.update(corrections)
            self.obs.observe("Decision", "W-2 corrected after completion",
                             "Recomputing with updated W-2 figures.", conf=0.95)
            return self._finalize_return(reask=False, prefix="Done — recomputed. ")

        # On-topic Q&A about the finished return.
        low = text.lower()
        r = self.result
        if r is not None and re.search(r"refund|owe|back|balance", low):
            if r.line_35a_refund > 0:
                return self.snapshot(
                    f"You're getting a refund of **{_money(r.line_35a_refund)}** "
                    "(line 34). It's on your downloadable 1040.")
            return self.snapshot(
                f"You owe **{_money(r.line_37_amount_owed)}** (line 37).")
        if r is not None and "deduction" in low:
            return self.snapshot(
                f"You're taking the **{_money(r.line_12_standard_deduction)}** "
                f"standard deduction for {r.filing_status_label} (line 12).")
        if r is not None and re.search(r"\btax\b|owe|taxable", low):
            return self.snapshot(
                f"Your total tax is **{_money(r.line_24_total_tax)}** on "
                f"{_money(r.line_15_taxable_income)} of taxable income (line 16).")
        return self.snapshot(
            "Your 2025 Form 1040 is ready to download. If anything looks off — "
            "your filing status or a W-2 figure — just tell me and I'll redo it.")

    # ── compute + fill PDF via the LangGraph pipeline ───────────────────────
    def _build_taxpayer(self) -> TaxpayerInfo:
        name = str(self.w2.get("employee_name", "") or "")
        parts = name.split(" ")
        return TaxpayerInfo(
            filing_status=self.info.get("filing_status") or T.SINGLE,
            num_dependents=int(self.info.get("num_dependents", 0) or 0),
            first_name=parts[0] if parts else "",
            last_name=" ".join(parts[1:]) if len(parts) > 1 else "",
            ssn=self.w2.get("employee_ssn", ""),
        )

    def _build_w2(self) -> W2:
        return W2(
            box1_wages=float(self.w2.get("box1_wages") or 0),
            box2_federal_withholding=float(self.w2.get("box2_federal_withholding") or 0),
            box3_ss_wages=self.w2.get("box3_ss_wages"),
            box4_ss_tax=self.w2.get("box4_ss_tax"),
            employee_name=self.w2.get("employee_name", ""),
            employer_name=self.w2.get("employer_name") or self.w2.get("employer") or "",
        )

    def _finalize_return(self, reask: bool = True, prefix: str = "") -> dict:
        from .agent import run_compute_graph  # local import avoids a cycle

        info = self._build_taxpayer()
        w2 = self._build_w2()
        self.result, self.pdf_path = run_compute_graph(self, w2, info)
        r = self.result

        self.obs.observe("Calculation", "Tax computed",
                         f"Taxable {_money(r.line_15_taxable_income)} → tax "
                         f"{_money(r.line_16_tax)} via the 2025 IRS "
                         f"{'Tax Table' if r.tax_method == 'tax_table' else 'Tax Computation Worksheet'}.",
                         conf=0.99)
        if r.line_35a_refund > 0:
            self.obs.observe("Decision", "Refund determined",
                             f"Payments {_money(r.line_33_total_payments)} exceed tax "
                             f"{_money(r.line_24_total_tax)} → refund "
                             f"{_money(r.line_35a_refund)}.", conf=0.99)
            outcome = f"you're getting a refund of **{_money(r.line_35a_refund)}**"
        else:
            self.obs.observe("Decision", "Balance due",
                             f"Tax {_money(r.line_24_total_tax)} exceeds payments "
                             f"{_money(r.line_33_total_payments)} → owe "
                             f"{_money(r.line_37_amount_owed)}.", conf=0.99)
            outcome = f"you owe **{_money(r.line_37_amount_owed)}**"

        self.phase = Phase.COMPLETE
        return self.snapshot(
            prefix + "All set — I've filled out your 2025 Form 1040. With "
            f"{_money(r.line_1a_wages)} in wages and the "
            f"{_money(r.line_12_standard_deduction)} standard deduction, your "
            f"taxable income is {_money(r.line_15_taxable_income)} and your tax is "
            f"{_money(r.line_16_tax)} — so {outcome}. You can download the "
            "completed form now." + (
                " Anything you'd like to change?" if reask else ""))

    # ── result shaped for the UI review card ────────────────────────────────
    def result_payload(self) -> Optional[dict]:
        r = self.result
        if r is None:
            return None
        is_refund = r.line_35a_refund > 0
        diff = r.line_35a_refund if is_refund else r.line_37_amount_owed
        lines = [
            {"line": "1a", "label": "Wages (W-2 box 1)", "value": _money(r.line_1a_wages)},
            {"line": "11", "label": "Adjusted gross income", "value": _money(r.line_11_agi)},
            {"line": "12", "label": "Standard deduction", "value": _money(r.line_12_standard_deduction)},
            {"line": "15", "label": "Taxable income", "value": _money(r.line_15_taxable_income)},
            {"line": "16", "label": "Tax", "value": _money(r.line_16_tax)},
        ]
        if r.line_19_ctc > 0:
            lines.append({"line": "19", "label": "Child tax credit", "value": "−" + _money(r.line_19_ctc)})
        lines += [
            {"line": "24", "label": "Total tax", "value": _money(r.line_24_total_tax)},
            {"line": "25", "label": "Federal tax withheld", "value": _money(r.line_25d_total_withholding)},
            {"line": "34" if is_refund else "37",
             "label": "Refund" if is_refund else "Amount you owe", "value": _money(diff)},
        ]
        return {
            "statusLabel": r.filing_status_label,
            "lines": lines,
            "isRefund": is_refund,
            "outcomeLabel": "Your refund" if is_refund else "You owe",
            "outcomeAmount": _money(diff),
        }

    def reset(self) -> None:
        self.__init__(self.session_id, self.tools.output_dir)
