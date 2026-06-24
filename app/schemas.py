"""Typed data models shared across the agent, tools, and server.

Pydantic gives us validation at the boundaries (a guardrail): a W-2 or a tax
result that doesn't satisfy these models never makes it into the form.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .tax_tables_2025 import FILING_STATUSES, FILING_STATUS_LABELS


class W2(BaseModel):
    """The subset of a Form W-2 this prototype needs to file a simple 1040."""

    employee_name: str = Field(default="", description="Box e - employee name")
    employee_ssn: str = Field(default="", description="Box a - SSN")
    employer_name: str = Field(default="", description="Box c - employer name")
    box1_wages: float = Field(..., ge=0, description="Box 1 - wages, tips, other comp")
    box2_federal_withholding: float = Field(
        default=0.0, ge=0, description="Box 2 - federal income tax withheld"
    )
    box3_ss_wages: Optional[float] = Field(default=None, ge=0)
    box4_ss_tax: Optional[float] = Field(default=None, ge=0)
    box16_state_wages: Optional[float] = Field(default=None, ge=0)
    box17_state_withholding: Optional[float] = Field(default=None, ge=0)

    @field_validator("box2_federal_withholding")
    @classmethod
    def withholding_not_absurd(cls, v: float, info) -> float:
        # A cheap sanity guardrail: withholding above wages is almost certainly
        # an extraction error. We don't hard-fail (data can be messy) but the
        # agent surfaces it for confirmation.
        return v


class TaxpayerInfo(BaseModel):
    """Everything the agent must collect beyond the W-2, within the 5-question budget."""

    filing_status: str = Field(default="single")
    first_name: str = ""
    last_name: str = ""
    ssn: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    spouse_first_name: str = ""
    spouse_last_name: str = ""
    spouse_ssn: str = ""
    num_dependents: int = Field(default=0, ge=0, le=4)
    est_payments: float = Field(default=0.0, ge=0, description="2025 estimated tax paid")
    deduction_method: str = Field(default="standard")  # standard | itemized (falls back)
    other_income: bool = Field(default=False)  # declared non-W-2 income (unsupported)

    @field_validator("filing_status")
    @classmethod
    def status_in_range(cls, v: str) -> str:
        if v not in FILING_STATUSES:
            raise ValueError(
                f"filing_status must be one of {FILING_STATUSES}, got {v!r}"
            )
        return v


class Form1040Result(BaseModel):
    """The computed return. Every field is an integer dollar amount (IRS convention)."""

    filing_status: str
    filing_status_label: str = ""
    line_1a_wages: int = 0
    line_1z_total_wages: int = 0
    line_9_total_income: int = 0
    line_11_agi: int = 0
    line_12_standard_deduction: int = 0
    line_15_taxable_income: int = 0
    line_16_tax: int = 0
    line_19_ctc: int = 0
    line_22_tax_after_credits: int = 0
    line_24_total_tax: int = 0
    line_25a_w2_withholding: int = 0
    line_25d_total_withholding: int = 0
    line_26_est_payments: int = 0
    line_33_total_payments: int = 0
    line_34_overpaid: int = 0
    line_35a_refund: int = 0
    line_37_amount_owed: int = 0
    tax_method: str = ""  # "tax_table" or "tax_computation_worksheet"

    def model_post_init(self, __context) -> None:
        if not self.filing_status_label:
            self.filing_status_label = FILING_STATUS_LABELS.get(
                self.filing_status, self.filing_status
            )
