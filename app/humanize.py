"""Claude-generated phrasing — warmth and variety, inside the guardrails.

The deterministic policy (conversation.py) decides *what* the agent says and owns
every number and the tax computation. This layer only **re-phrases** that message
so it sounds warm, human, and a little different each time — never changing a
figure, the question, or the meaning.

Safety (the "within our guardrails" part):
  * Every dollar amount in the original MUST appear verbatim in the rewrite, or we
    discard the rewrite and return the deterministic text. The LLM can reword, not
    re-number.
  * No new tax claims/advice are allowed (instructed) and the rewrite is length-
    bounded.
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
    "- Keep any **bold** markdown exactly around the same values.\n"
    "- Ask the SAME question and keep the SAME meaning. Do not add new facts, numbers, "
    "or any tax/financial advice. Do not remove a disclaimer if one is present.\n"
    "- Keep it concise (roughly the same length, at most a sentence or two longer).\n"
    "- Return ONLY the rewritten message, no quotes or preamble."
)


def humanize(message: str) -> str:
    """Return a warm, varied rewrite of `message`, or `message` itself on any doubt."""
    if not message or os.environ.get("LLM_PHRASING", "1") == "0":
        return message
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return message
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("CHAT_MODEL", "claude-haiku-4-5")
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            temperature=1.0,  # variety run-to-run
            system=_SYSTEM,
            messages=[{"role": "user", "content": message}],
        )
        out = "".join(
            p.text for p in resp.content if getattr(p, "type", "") == "text"
        ).strip()
    except Exception:
        return message

    if not out:
        return message
    # Guardrail: no dollar amount may be dropped or altered.
    original_amounts = _DOLLAR.findall(message)
    rewritten_amounts = _DOLLAR.findall(out)
    if not _multiset_subset(original_amounts, rewritten_amounts):
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
