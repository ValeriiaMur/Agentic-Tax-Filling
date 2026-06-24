"""Guardrails: constraints enforced in code, not just asked for in the prompt.

Four concrete guardrails live here:
  1. QuestionBudget   - hard cap of 5 questions, counted in code.
  2. classify_scope   - keeps the agent on the tax-filing task; off-task or
                        tax-advice requests are flagged so the agent can decline.
  3. parse_filing_status - deterministic mapping of free text to a valid status,
                        so the radio button on the form is never guessed by the LLM.
  4. validate_w2_payload - rejects/【flags malformed W-2 data before it can reach
                        the tax engine or the PDF.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from . import tax_tables_2025 as T


class QuestionBudget:
    """Hard limit on questions asked of the user, enforced by the agent loop."""

    def __init__(self, limit: int = 5):
        self.limit = limit
        self.asked = 0

    def can_ask(self) -> bool:
        return self.asked < self.limit

    def record_question(self) -> None:
        self.asked += 1

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.asked)


# Phrases that indicate the user is asking for advice / something off-task.
_OUT_OF_SCOPE_PATTERNS = [
    r"\bshould i invest\b",
    r"\binvest in\b",
    r"\bwhat stocks?\b",
    r"\bbuy stocks?\b",
    r"\broth ira\b",
    r"\bindex funds?\b",
    r"\btax advice\b",
    r"\bdepreciat",
    r"\brental property\b",
    r"\bcrypto\b",
    r"\bwrite (me )?a poem\b",
    r"\bhack\b",
]


def classify_scope(text: str) -> str:
    """Return 'out_of_scope' or 'on_task' for a user message."""
    low = text.lower()
    for pat in _OUT_OF_SCOPE_PATTERNS:
        if re.search(pat, low):
            return "out_of_scope"
    return "on_task"


def parse_filing_status(text: str) -> Optional[str]:
    """Deterministically map free text to a valid 2025 filing status."""
    low = text.lower()
    # order matters: check the more specific married phrasings first
    if re.search(r"separat", low) and "married" in low:
        return T.MFS
    if re.search(r"\bmfs\b", low):
        return T.MFS
    if re.search(r"joint|together|\bmfj\b", low):
        return T.MFJ
    if re.search(r"head of household|\bhoh\b", low):
        return T.HOH
    if re.search(r"surviving spouse|widow|\bqss\b", low):
        return T.QSS
    # Negations and "single" must be checked before the bare "married" fallback.
    if re.search(r"not married|unmarried|\bsingle\b", low):
        return T.SINGLE
    if "married" in low:
        # "married" with no qualifier defaults to jointly (most common)
        return T.MFJ
    return None


def validate_w2_payload(payload: dict) -> Tuple[bool, List[str]]:
    """Validate a raw W-2 dict before it becomes a typed W2. Returns (ok, issues)."""
    issues: List[str] = []
    wages = payload.get("box1_wages")
    wh = payload.get("box2_federal_withholding", 0) or 0

    if wages is None:
        issues.append("Box 1 wages are required but were not found.")
        return False, issues
    try:
        wages = float(wages)
        wh = float(wh)
    except (TypeError, ValueError):
        issues.append("Wages and withholding must be numbers.")
        return False, issues

    if wages < 0:
        issues.append("Box 1 wages cannot be negative.")
    if wh < 0:
        issues.append("Box 2 withholding cannot be negative.")
    if wages > 0 and wh > wages:
        issues.append(
            "Federal withholding exceeds total wages, which is unusual - "
            "this looks like a misread and should be confirmed."
        )
    if wages > 25_000_000:
        issues.append("Wages are implausibly large; please confirm.")

    return (len(issues) == 0), issues
