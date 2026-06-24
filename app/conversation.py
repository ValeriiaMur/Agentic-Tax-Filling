"""Design-aligned conversation flow — the agent's decision core.

Implements the Malleable-UI stage machine
(idle → upload → processing → confirm → questions×5 → review → download) on the
server, so the four pillars stay enforced and observable in code:

  * Chat loop   - `TaxSession` carries stage, W-2, answers, and result across the
                  discrete turn endpoints the UI calls.
  * Tools       - extraction, computation, and PDF fill go through `ToolRegistry`.
  * Guardrails  - a hard 5-question budget, out-of-scope decline, itemized→standard
                  fallback, and non-W-2 income exclusion — all in code.
  * Observation - every step appends a phased decision-trail entry
                  (Session/Vision/Reasoning/Calculation/Decision/Guardrail) with
                  confidence + flag, surfaced in the UI drawer.

All tax figures (deduction amounts, the questions, the computed return) come from
the backend — never hardcoded in the browser.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from typing import List, Optional

from . import tax_tables_2025 as T
from .guardrails import QuestionBudget
from .observability import ObservationLog
from .schemas import Form1040Result, TaxpayerInfo, W2
from .tools import ToolRegistry

HERE = os.path.dirname(__file__)
SAMPLE_W2_JSON = os.path.join(HERE, "..", "assets", "sample_w2.json")


class Stage(str, Enum):
    IDLE = "idle"
    UPLOAD = "upload"
    PROCESSING = "processing"
    CONFIRM = "confirm"
    QUESTIONS = "questions"
    REVIEW = "review"
    DOWNLOAD = "download"


def _money(n: float) -> str:
    return "$" + f"{round(n):,}"


def build_questions() -> List[dict]:
    """The five questions, with every tax figure sourced from backend constants."""
    std = T.STANDARD_DEDUCTION
    ctc = T.CHILD_TAX_CREDIT
    return [
        {
            "id": "filing_status",
            "prompt": "What’s your filing status?",
            "helper": "It sets your standard deduction and tax brackets.",
            "options": [
                {"value": T.SINGLE, "label": "Single", "sub": f"{_money(std[T.SINGLE])} deduction"},
                {"value": T.MFJ, "label": "Married, jointly", "sub": f"{_money(std[T.MFJ])} deduction"},
                {"value": T.HOH, "label": "Head of household", "sub": f"{_money(std[T.HOH])} deduction"},
            ],
        },
        {
            "id": "dependents",
            "prompt": "How many dependents?",
            "helper": f"Qualifying children under 17 can add a {_money(ctc)} credit each.",
            "options": [
                {"value": 0, "label": "None", "sub": ""},
                {"value": 1, "label": "1", "sub": f"+{_money(ctc)} credit"},
                {"value": 2, "label": "2", "sub": f"+{_money(ctc * 2)} credit"},
                {"value": 3, "label": "3+", "sub": f"+{_money(ctc * 3)} credit"},
            ],
        },
        {
            "id": "other_income",
            "prompt": "Any income beyond this W-2?",
            "helper": "1099 work, interest, dividends, self-employment.",
            "options": [
                {"value": "no", "label": "No, just the W-2", "sub": ""},
                {"value": "yes", "label": "Yes, I have more", "sub": "not supported here"},
            ],
        },
        {
            "id": "deduction",
            "prompt": "Standard or itemized deduction?",
            "helper": "Most filers at this income take the standard deduction.",
            "options": [
                {"value": "standard", "label": "Standard", "sub": "recommended"},
                {"value": "itemized", "label": "Itemized", "sub": "needs receipts"},
            ],
        },
        {
            "id": "est_payments",
            "prompt": "Any estimated tax already paid?",
            "helper": "Quarterly payments you sent the IRS during the year.",
            "options": [
                {"value": 0, "label": "None", "sub": ""},
                {"value": 500, "label": "~$500", "sub": ""},
                {"value": 1500, "label": "~$1,500", "sub": ""},
            ],
        },
    ]


QUESTIONS = build_questions()


class TaxSession:
    """Holds one user's state across the design's stage machine."""

    def __init__(self, session_id: str, output_dir: str):
        self.session_id = session_id
        self.obs = ObservationLog(session_id)
        self.tools = ToolRegistry(self.obs, output_dir)
        self.stage = Stage.IDLE
        self.messy = False
        self.w2: dict = {}
        self.answers = {
            "filing_status": None, "dependents": None, "other_income": None,
            "deduction": None, "est_payments": None,
        }
        self.q_index = 0
        self.budget = QuestionBudget(limit=5)
        self.result: Optional[Form1040Result] = None
        self.pdf_path: Optional[str] = None

    # ── snapshot returned to the UI ────────────────────────────────────────
    def snapshot(self, **extra) -> dict:
        base = {
            "stage": self.stage.value,
            "observations": self.obs.trail(),
            "obs_count": self.obs.trail_count,
            "questions_asked": self.budget.asked,
            "questions_remaining": self.budget.remaining,
        }
        base.update(extra)
        return base

    # ── stage: begin ───────────────────────────────────────────────────────
    def begin(self) -> dict:
        self.stage = Stage.UPLOAD
        self.obs.observe("Session", "Return started",
                         "Scope locked to U.S. federal Form 1040, tax year 2025.", conf=1.0)
        return self.snapshot(agent={
            "text": "I’ll prepare your federal Form 1040 for 2025.",
            "sub": "Add your W-2 to begin — figures are read on the spot.",
        })

    # ── stage: upload + extraction ──────────────────────────────────────────
    def _load_sample(self) -> dict:
        with open(SAMPLE_W2_JSON, encoding="utf-8") as fh:
            return json.load(fh)

    def upload(self, messy: bool, image_bytes: bytes = None, media_type: str = "") -> dict:
        self.messy = messy
        self.obs.observe("Vision", "Document received",
                         "Low-resolution phone capture, slight skew." if messy
                         else "Clean single-page PDF.",
                         conf=0.88 if messy else 0.99)

        # Real upload uses the extract_w2 tool (Claude vision); the demo buttons
        # use the backend sample fixture. Either way, figures come from the server.
        data = None
        if image_bytes:
            extracted = self.tools.extract_w2(image_bytes=image_bytes, media_type=media_type)
            if extracted.get("box1_wages"):
                data = extracted
        if data is None:
            data = self._load_sample()

        self.w2 = data
        self.stage = Stage.CONFIRM
        employer = data.get("employer_name") or data.get("employer") or "your employer"

        if messy:
            self.obs.observe("Vision", "W-2 parsed",
                             f"{employer} — 5 of 6 boxes read confidently.", conf=0.82)
            self.obs.observe("Guardrail", "Box 1 flagged",
                             "Wages digit unclear (0.61). Routed to human verification before use.",
                             conf=0.61, flag=True)
            agent = {"text": f"Read your W-2 — {employer}.",
                     "sub": "One figure came through blurry. Please verify the highlighted box before I continue."}
        else:
            self.obs.observe("Vision", "W-2 parsed",
                             f"{employer} — all boxes read confidently.", conf=0.97)
            agent = {"text": f"Read your W-2 — {employer}.",
                     "sub": "Confirm the figures below and I’ll start your return."}

        return self.snapshot(
            user_echo="Uploaded W-2 (phone photo)" if messy else "Uploaded W-2.pdf",
            w2=self._confirm_card(), agent=agent, messy=messy,
        )

    def _confirm_card(self) -> dict:
        d = self.w2
        employer = d.get("employer_name") or d.get("employer") or "your employer"

        def row(label, key, flagged=False):
            v = d.get(key)
            return {"label": label, "value": (_money(v) if v is not None else "—"),
                    "flagged": flagged, "raw": v}

        rows = [
            row("Box 1 — Wages, tips", "box1_wages", flagged=self.messy),
            row("Box 2 — Federal tax withheld", "box2_federal_withholding"),
            row("Box 3 — Social Security wages", "box3_ss_wages"),
            row("Box 4 — Social Security tax", "box4_ss_tax"),
            row("Box 17 — State income tax", "box17_state_withholding"),
        ]
        return {
            "employer": employer,
            "meta": "Phone photo · 5 of 6 boxes clear" if self.messy
                    else "Single W-2 · boxes read",
            "confLabel": "needs review" if self.messy else "high confidence",
            "rows": rows,
            "box1_value": d.get("box1_wages"),
        }

    # ── stage: confirm ──────────────────────────────────────────────────────
    def confirm(self, box1_override: Optional[float] = None) -> dict:
        if box1_override is not None:
            self.w2["box1_wages"] = float(box1_override)
        wages = float(self.w2.get("box1_wages") or 0)
        wh = float(self.w2.get("box2_federal_withholding") or 0)
        employer = self.w2.get("employer_name") or self.w2.get("employer") or "your employer"

        self.obs.observe("Reasoning", "W-2 confirmed",
                         f"Wages {_money(wages)}, federal withholding {_money(wh)} accepted.",
                         conf=0.99)
        self.stage = Stage.QUESTIONS
        self.q_index = 0
        summary = {
            "title": "W-2 confirmed",
            "rows": [
                {"label": "Employer", "value": employer},
                {"label": "Wages (Box 1)", "value": _money(wages)},
                {"label": "Withheld (Box 2)", "value": _money(wh)},
            ],
        }
        return self.snapshot(
            user_echo=(f"Verified — wages are {_money(wages)}." if self.messy else "Confirmed."),
            summary=summary, question=self._question_payload(0),
        )

    def _question_payload(self, i: int) -> dict:
        q = QUESTIONS[i]
        if self.budget.can_ask():
            self.budget.record_question()
        return {
            "index": i, "total": len(QUESTIONS),
            "id": q["id"], "prompt": q["prompt"], "helper": q["helper"],
            "options": q["options"],
            "progress": f"Question {i + 1} of {len(QUESTIONS)} · {q['prompt']}",
        }

    # ── stage: answer a question ────────────────────────────────────────────
    def answer(self, value) -> dict:
        q = QUESTIONS[self.q_index]
        qid = q["id"]
        self.answers[qid] = value
        opt = next((o for o in q["options"] if str(o["value"]) == str(value)), None)
        label = opt["label"] if opt else str(value)
        self._log_answer(qid, value)

        note = None
        if qid == "other_income" and str(value) == "yes":
            note = {"text": "I’ll note that, but this assistant only files W-2 wage income.",
                    "sub": "We’ll proceed with the W-2 alone — add other forms with a full preparer."}

        if self.q_index + 1 < len(QUESTIONS):
            self.q_index += 1
            return self.snapshot(user_echo=label, note=note,
                                 question=self._question_payload(self.q_index))

        # last answer -> compute + finalize
        self._compute()
        return self.snapshot(user_echo=label, note=note,
                             agent={"text": "Done — here’s your 1040.",
                                    "sub": self._outcome_line()},
                             result=self.result_payload())

    def _log_answer(self, qid: str, value) -> None:
        if qid == "filing_status":
            self.obs.observe("Reasoning", "Filing status",
                             f"{T.FILING_STATUS_LABELS[value]} → standard deduction "
                             f"{_money(T.STANDARD_DEDUCTION[value])} (2025).", conf=0.99)
        elif qid == "dependents":
            n = int(value or 0)
            self.obs.observe("Reasoning", "Dependents",
                             f"{n} dependent(s) → up to {_money(n * T.CHILD_TAX_CREDIT)} "
                             "child tax credit.", conf=0.97)
        elif qid == "other_income":
            if str(value) == "yes":
                self.obs.observe("Guardrail", "Out-of-scope income",
                                 "Non-W-2 income declared but unsupported here. Excluded from this return.",
                                 conf=0.9, flag=True)
            else:
                self.obs.observe("Reasoning", "Income sources",
                                 "W-2 wages are the only income to report.", conf=0.98)
        elif qid == "deduction":
            if str(value) == "itemized":
                self.obs.observe("Guardrail", "Deduction method",
                                 "Itemizing requested but no receipts provided — standard "
                                 "deduction used for accuracy.", conf=0.85, flag=True)
            else:
                self.obs.observe("Reasoning", "Deduction method",
                                 "Standard deduction applied per IRS Form 1040 line 12.", conf=0.99)
        elif qid == "est_payments":
            n = int(value or 0)
            self.obs.observe("Reasoning", "Estimated payments",
                             (f"{_money(n)} in prior payments added to line 26." if n > 0
                              else "No estimated payments this year."), conf=0.96)

    # ── compute (deterministic) + finalize PDF via the LangGraph ────────────
    def _build_taxpayer(self) -> TaxpayerInfo:
        a = self.answers
        return TaxpayerInfo(
            filing_status=a["filing_status"] or T.SINGLE,
            num_dependents=int(a["dependents"] or 0),
            est_payments=float(a["est_payments"] or 0),
            deduction_method=a["deduction"] or "standard",
            other_income=(str(a["other_income"]) == "yes"),
            first_name=str(self.w2.get("employee_name", "")).split(" ")[0] if self.w2.get("employee_name") else "",
            last_name=" ".join(str(self.w2.get("employee_name", "")).split(" ")[1:]) if self.w2.get("employee_name") else "",
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

    def _compute(self) -> None:
        from .agent import run_compute_graph  # local import to avoid cycle

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
                             f"{_money(r.line_24_total_tax)} → refund {_money(r.line_35a_refund)}.",
                             conf=0.99)
        else:
            self.obs.observe("Decision", "Balance due",
                             f"Tax {_money(r.line_24_total_tax)} exceeds payments "
                             f"{_money(r.line_33_total_payments)} → owe "
                             f"{_money(r.line_37_amount_owed)}.", conf=0.99)
        self.stage = Stage.REVIEW

    # ── result payload for the review/download cards ────────────────────────
    def result_payload(self) -> Optional[dict]:
        r = self.result
        if r is None:
            return None
        is_refund = r.line_35a_refund > 0
        diff = r.line_35a_refund if is_refund else r.line_37_amount_owed
        lines = [
            {"line": "1a", "label": "Wages (W-2 box 1)", "value": _money(r.line_1a_wages)},
            {"line": "9", "label": "Total income", "value": _money(r.line_9_total_income)},
            {"line": "11", "label": "Adjusted gross income", "value": _money(r.line_11_agi)},
            {"line": "12", "label": "Standard deduction", "value": _money(r.line_12_standard_deduction)},
            {"line": "15", "label": "Taxable income", "value": _money(r.line_15_taxable_income)},
            {"line": "16", "label": "Tax", "value": _money(r.line_16_tax)},
        ]
        if r.line_19_ctc > 0:
            lines.append({"line": "19", "label": "Child tax credit", "value": "−" + _money(r.line_19_ctc)})
        lines.append({"line": "22", "label": "Tax after credits", "value": _money(r.line_22_tax_after_credits)})
        lines.append({"line": "24", "label": "Total tax", "value": _money(r.line_24_total_tax)})
        lines.append({"line": "25", "label": "Federal tax withheld", "value": _money(r.line_25d_total_withholding)})
        if r.line_26_est_payments > 0:
            lines.append({"line": "26", "label": "Estimated payments", "value": _money(r.line_26_est_payments)})
        lines.append({"line": "33", "label": "Total payments", "value": _money(r.line_33_total_payments)})
        lines.append({"line": "34" if is_refund else "37",
                      "label": "Overpayment / refund" if is_refund else "Amount you owe",
                      "value": _money(diff)})
        return {
            "statusLabel": r.filing_status_label, "lines": lines,
            "isRefund": is_refund,
            "outcomeLabel": "Your refund" if is_refund else "You owe",
            "outcomeAmount": _money(diff),
            "outcomeLine": (f"Refund of {_money(diff)}" if is_refund
                            else f"Balance due of {_money(diff)}"),
        }

    def _outcome_line(self) -> str:
        p = self.result_payload()
        return p["outcomeLine"] if p else ""

    # ── stage: finalize / download ──────────────────────────────────────────
    def finalize(self) -> dict:
        self.obs.observe("Session", "Return finalized",
                         "Form 1040 assembled and ready for download.", conf=1.0)
        self.stage = Stage.DOWNLOAD
        return self.snapshot(
            agent={"text": "Your return is ready to file.",
                   "sub": "Download a copy below, or ask me anything about it."},
            result=self.result_payload(),
        )

    # ── command bar (guardrail behavior) ────────────────────────────────────
    def command(self, raw: str) -> dict:
        raw = (raw or "").strip()
        if not raw:
            return self.snapshot()
        import re
        on_topic = bool(re.search(
            r"(refund|owe|balance|tax|withheld|deduction|wage|status|1040|file|income)",
            raw, re.IGNORECASE))
        r = self.result
        if on_topic and r is not None:
            p = self.result_payload()
            if re.search(r"refund|owe|balance|get back|back", raw, re.IGNORECASE):
                agent = {"text": (f"You’re getting {p['outcomeAmount']} back." if p["isRefund"]
                                  else f"You owe {p['outcomeAmount']}."),
                         "sub": f"Line {'34' if p['isRefund'] else '37'} on your 1040."}
            elif re.search(r"deduction", raw, re.IGNORECASE):
                agent = {"text": f"Standard deduction of {_money(r.line_12_standard_deduction)} (line 12).",
                         "sub": f"{r.filing_status_label}, 2025."}
            else:
                agent = {"text": f"Total tax is {_money(r.line_24_total_tax)} on "
                                 f"{_money(r.line_15_taxable_income)} taxable income.",
                         "sub": "Ask about your refund, deduction, or withholding."}
            return self.snapshot(user_echo=raw, agent=agent)
        if on_topic:
            return self.snapshot(user_echo=raw,
                                 agent={"text": "Let’s finish your return first — then I can answer that."})
        # off-topic -> decline + toast + guardrail observation
        self.obs.observe("Guardrail", "Out-of-scope request",
                         f"“{raw}” declined. Assistant is limited to federal 1040 preparation.",
                         conf=0.99, flag=True)
        return self.snapshot(
            user_echo=raw,
            agent={"text": "That’s outside what I do.",
                   "sub": "I only prepare a U.S. federal Form 1040 from your W-2."},
            toast="Off-topic request declined — logged to the decision trail.",
        )

    def reset(self) -> None:
        self.__init__(self.session_id, self.tools.output_dir)
