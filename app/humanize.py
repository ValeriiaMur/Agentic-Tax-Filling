"""Claude-generated phrasing — warmth and variety, inside the guardrails.

The deterministic policy (conversation.py) decides *what* the agent says and owns
every number and the tax computation. This layer only **re-phrases** that message
so it sounds warm, human, and a little different each time — never changing a
figure, the question, or the meaning.

Privacy: the only PII that could appear in an outgoing message is the taxpayer's
name. We **mask it locally before the call** (replace with a neutral placeholder)
and **restore it after**, so the person's name is never sent to the model. Tax
math, SSNs, and addresses never reach this layer at all.

Safety (the "within our guardrails" part):
  * Every dollar amount in the original MUST appear verbatim in the rewrite, or we
    discard the rewrite and return the deterministic text.
  * No new tax claims/advice (instructed); the rewrite is length-bounded.
  * Any error, missing key, or failed check → silent fallback to the template, so
    the conversation never breaks and works offline with no key.

Enabled when ANTHROPIC_API_KEY is set; disable with LLM_PHRASING=0.
"""

from __future__ import annotations

import os
import re

_DOLLAR = re.compile(r"\$[\d,]+(?:\.\d+)?")

_SYSTEM = (
    "You rewrite one message from a friendly assistant that helps someone fill out "
    "their U.S. federal Form 1040 (tax year 2025) from a W-2. Rewrite the message so "
    "it sounds warm, natural, and human — like a helpful person, not a form. Vary "
    "the wording so it doesn't read the same every time.\n\n"
    "HARD RULES:\n"
    "- Preserve every dollar amount, number, percentage, box reference (e.g. 'Box 1'), "
    "and line reference (e.g. 'line 12') EXACTLY as written.\n"
    "- Keep any placeholder token like ⟦NAME0⟧ EXACTLY as-is; do not translate or remove it.\n"
    "- Keep any **bold** markdown exactly around the same values.\n"
    "- Ask the SAME question and keep the SAME meaning. Do not add new facts, numbers, "
    "or any tax/financial advice. Do not remove a disclaimer if one is present.\n"
    "- Keep it concise (roughly the same length, at most a sentence or two longer).\n"
    "- Return ONLY the rewritten message, no quotes or preamble."
)


def _mask(message: str, terms) -> tuple[str, dict]:
    """Replace PII `terms` in `message` with neutral placeholders.

    Returns (masked_message, holders) where holders maps placeholder -> original.
    Longer terms are masked first so a full name is replaced before its first name.
    """
    holders: dict = {}
    masked = message
    uniq = sorted({t for t in (terms or []) if t and t in message}, key=len, reverse=True)
    for i, term in enumerate(uniq):
        ph = f"⟦NAME{i}⟧"
        holders[ph] = term
        masked = masked.replace(term, ph)
    return masked, holders


def humanize(message: str, redact_terms=None) -> str:
    """Return a warm, varied rewrite of `message`, or `message` itself on any doubt.

    `redact_terms` are PII strings (e.g. the taxpayer's name) masked before the
    model call and restored afterward, so they are never transmitted.
    """
    if not message or os.environ.get("LLM_PHRASING", "1") == "0":
        return message
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return message

    masked, holders = _mask(message, redact_terms)
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("CHAT_MODEL", "claude-haiku-4-5")
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            temperature=1.0,  # variety run-to-run
            system=_SYSTEM,
            messages=[{"role": "user", "content": masked}],
        )
        out = "".join(
            p.text for p in resp.content if getattr(p, "type", "") == "text"
        ).strip()
    except Exception:
        return message

    if not out:
        return message
    # Restore any masked PII locally.
    for ph, term in holders.items():
        out = out.replace(ph, term)
    # If the model invented or left a stray placeholder we can't resolve, bail out.
    if "⟦NAME" in out:
        return message
    # Guardrail: no dollar amount may be dropped or altered.
    if not _multiset_subset(_DOLLAR.findall(message), _DOLLAR.findall(out)):
        return message
    # Length sanity — reject runaway rewrites.
    if len(out) > max(420, int(len(message) * 2.2)):
        return message
    return out


def _multiset_subset(needles: list[str], haystack: list[str]) -> bool:
    """True if every value in `needles` appears in `haystack` (with multiplicity)."""
    pool = list(haystack)
    for n in needles:
        if n in pool:
            pool.remove(n)
        else:
            return False
    return True
