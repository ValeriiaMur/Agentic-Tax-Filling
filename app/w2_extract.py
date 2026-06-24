"""W-2 extraction tool: Claude vision primary, deterministic parser fallback.

Two entry points:
  * extract_w2_from_image  - sends an uploaded W-2 image/PDF to Claude vision and
                             returns structured box values. Used when a key is set.
  * parse_w2_text          - a regex parser for pasted/typed W-2 figures. This is
                             the offline fallback and keeps the whole system
                             working end-to-end with no LLM key.

Both return a plain dict that is then validated by guardrails.validate_w2_payload
and coerced into the typed W2 model. Extraction never computes tax and never
writes the form; it only proposes values for the user to confirm.
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Optional

# Cost-friendly default for structured W-2 box extraction. A misread never reaches
# the form (user confirms, engine is deterministic), so Haiku is a safe default;
# set VISION_MODEL=claude-sonnet-4-6 for more extraction headroom.
VISION_MODEL = os.environ.get("VISION_MODEL", "claude-haiku-4-5")

_NUM = r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)"


def _to_float(s: str) -> float:
    return float(s.replace(",", "").replace("$", "").strip())


def parse_w2_text(text: str) -> dict:
    """Best-effort deterministic extraction of W-2 figures from free text."""
    out: dict = {"box1_wages": None, "box2_federal_withholding": 0.0}
    low = text.lower()

    # Box 1 wages
    m = re.search(r"box\s*1[^0-9$]*" + _NUM, low) or re.search(
        r"wages?[^0-9$]*" + _NUM, low
    )
    if m:
        out["box1_wages"] = _to_float(m.group(1))

    # Box 2 federal withholding
    m = re.search(r"box\s*2[^0-9$]*" + _NUM, low) or re.search(
        r"(?:federal\s*(?:income\s*tax\s*)?withh?olding|withheld)[^0-9$]*" + _NUM, low
    )
    if m:
        out["box2_federal_withholding"] = _to_float(m.group(1))

    # Employee name (best effort)
    m = re.search(r"employee[:\s]+([A-Za-z][A-Za-z .'-]+)", text, re.IGNORECASE)
    if m:
        out["employee_name"] = m.group(1).strip()

    return out


_VISION_PROMPT = (
    "You are reading a U.S. Form W-2. Extract ONLY these fields and return strict "
    "JSON with these keys: employee_name (string), employee_ssn (string), "
    "employer_name (string), box1_wages (number), box2_federal_withholding (number), "
    "box16_state_wages (number or null), box17_state_withholding (number or null). "
    "Use numbers without commas or dollar signs. Do not guess; if a field is not "
    "visible, use null. Return JSON only, no prose."
)


def extract_w2_from_image(
    image_bytes: bytes, media_type: str, client=None
) -> dict:
    """Extract W-2 fields from an image/PDF using Claude vision.

    Raises RuntimeError if no API key/client is available so the caller can fall
    back to the form/paste path.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if client is None:
        if not api_key:
            raise RuntimeError("No ANTHROPIC_API_KEY; use the form/paste fallback.")
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    if media_type == "application/pdf":
        source = {"type": "base64", "media_type": "application/pdf", "data": b64}
        block = {"type": "document", "source": source}
    else:
        source = {"type": "base64", "media_type": media_type, "data": b64}
        block = {"type": "image", "source": source}

    msg = client.messages.create(
        model=VISION_MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": [block, {"type": "text", "text": _VISION_PROMPT}]}],
    )
    raw = "".join(part.text for part in msg.content if getattr(part, "type", "") == "text")
    return _coerce_vision_json(raw)


def _coerce_vision_json(raw: str) -> dict:
    """Parse the model's JSON, tolerating code fences or stray prose."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"Vision model did not return JSON: {raw[:200]}")
    data = json.loads(m.group(0))
    # normalize numbers
    for k in ("box1_wages", "box2_federal_withholding", "box16_state_wages",
              "box17_state_withholding"):
        if data.get(k) is not None:
            try:
                data[k] = float(str(data[k]).replace(",", "").replace("$", ""))
            except (TypeError, ValueError):
                data[k] = None
    if data.get("box2_federal_withholding") is None:
        data["box2_federal_withholding"] = 0.0
    return data
