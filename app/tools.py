"""The agent's tool registry — real actions, each observable.

Every tool call and result is recorded on the session's ObservationLog, so the
Tools pillar and the Observation pillar reinforce each other: you can see, in
order, every action the agent took and what it returned.
"""

from __future__ import annotations

import os
from typing import Optional

from .observability import ObservationLog
from .pdf_fill import fill_1040
from .schemas import Form1040Result, TaxpayerInfo, W2
from .tax_engine import compute_1040
from .w2_extract import extract_w2_from_image, parse_w2_text


class ToolRegistry:
    """Wraps the agent's real tools and logs each invocation."""

    def __init__(self, obs: ObservationLog, output_dir: str):
        self.obs = obs
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def extract_w2(
        self, *, image_bytes: Optional[bytes] = None, media_type: str = "",
        text: str = "",
    ) -> dict:
        """Extract W-2 fields from an image/PDF (vision) or pasted text (fallback)."""
        if image_bytes:
            self.obs.tool_call("extract_w2", source="vision", media_type=media_type)
            try:
                data = extract_w2_from_image(image_bytes, media_type)
                self.obs.tool_result("extract_w2", source="vision", **_safe(data))
                return data
            except Exception as e:  # vision unavailable or failed -> fallback
                self.obs.guardrail("vision_fallback", reason=str(e)[:120])
        self.obs.tool_call("extract_w2", source="text")
        data = parse_w2_text(text)
        self.obs.tool_result("extract_w2", source="text", **_safe(data))
        return data

    def compute_1040(self, w2: W2, info: TaxpayerInfo) -> Form1040Result:
        self.obs.tool_call(
            "compute_1040", filing_status=info.filing_status, wages=w2.box1_wages,
            withholding=w2.box2_federal_withholding,
        )
        result = compute_1040(w2, info)
        self.obs.tool_result(
            "compute_1040", taxable_income=result.line_15_taxable_income,
            tax=result.line_16_tax, method=result.tax_method,
            refund=result.line_35a_refund, amount_owed=result.line_37_amount_owed,
        )
        return result

    def fill_1040_pdf(self, result: Form1040Result, info: TaxpayerInfo, w2: W2) -> str:
        out = os.path.join(self.output_dir, f"form1040_{self.obs.session_id}.pdf")
        self.obs.tool_call("fill_1040_pdf", output=os.path.basename(out))
        path = fill_1040(result, info, w2, out)
        self.obs.tool_result("fill_1040_pdf", path=os.path.basename(path), bytes=os.path.getsize(path))
        return path


def _safe(d: dict) -> dict:
    return {k: v for k, v in d.items() if k in (
        "box1_wages", "box2_federal_withholding", "employee_name")}
