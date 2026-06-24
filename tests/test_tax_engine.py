"""Golden tests for the 2025 tax engine.

Expected values are taken DIRECTLY from the official IRS 2025 Tax Table
(Form 1040 instructions, i1040gi). Columns in the table are:
Single | Married filing jointly | Married filing separately | Head of household.

Verified rows used below:
  26,250-26,300 -> Single 2,915 | MFJ 2,676 | MFS 2,915 | HOH 2,813
   8,500- 8,550 -> all statuses 853
  33,300-33,350 -> Single 3,761 | MFJ 3,522 | MFS 3,761 | HOH 3,659

If the engine ever drifts from these, it no longer matches the IRS table.
"""

import pytest

from app.schemas import TaxpayerInfo, W2
from app.tax_engine import compute_1040, compute_tax
from app import tax_tables_2025 as T


# --- compute_tax matches the official Tax Table to the dollar ---------------

@pytest.mark.parametrize(
    "taxable,status,expected",
    [
        (26_250, T.SINGLE, 2_915),
        (26_250, T.MFJ, 2_676),
        (26_250, T.MFS, 2_915),
        (26_250, T.HOH, 2_813),
        (8_500, T.SINGLE, 853),
        (8_500, T.MFJ, 853),
        (8_500, T.HOH, 853),
        (33_300, T.SINGLE, 3_761),
        (33_300, T.MFJ, 3_522),
        (33_300, T.HOH, 3_659),
    ],
)
def test_tax_table_matches_irs(taxable, status, expected):
    tax, method = compute_tax(taxable, status)
    assert tax == expected
    assert method == "tax_table"


def test_zero_taxable_income_is_zero_tax():
    assert compute_tax(0, T.SINGLE) == (0, "tax_table")
    assert compute_tax(-500, T.SINGLE) == (0, "tax_table")


def test_high_income_uses_computation_worksheet():
    tax, method = compute_tax(150_000, T.SINGLE)
    assert method == "tax_computation_worksheet"
    # 0.10*11925 + 0.12*(48475-11925) + 0.22*(103350-48475) + 0.24*(150000-103350)
    # = 1192.5 + 4386 + 12072.5 + 11196 = 28847
    assert tax == 28_847


# --- Full 1040 for the target profile (~$40k single W-2) --------------------

def test_full_return_single_40k_refund():
    w2 = W2(box1_wages=42_000, box2_federal_withholding=4_200, employee_name="Jordan Rivera")
    info = TaxpayerInfo(filing_status=T.SINGLE)
    r = compute_1040(w2, info)

    assert r.line_1a_wages == 42_000
    assert r.line_9_total_income == 42_000
    assert r.line_11_agi == 42_000
    assert r.line_12_standard_deduction == 15_750
    assert r.line_15_taxable_income == 26_250
    assert r.line_16_tax == 2_915          # IRS table
    assert r.line_24_total_tax == 2_915
    assert r.line_25d_total_withholding == 4_200
    assert r.line_34_overpaid == 1_285     # 4200 - 2915
    assert r.line_35a_refund == 1_285
    assert r.line_37_amount_owed == 0


def test_full_return_married_jointly_changes_deduction():
    w2 = W2(box1_wages=42_000, box2_federal_withholding=4_200)
    info = TaxpayerInfo(filing_status=T.MFJ)
    r = compute_1040(w2, info)

    assert r.line_12_standard_deduction == 31_500
    assert r.line_15_taxable_income == 10_500   # 42000 - 31500
    # row 10,500-10,550 midpoint 10,525, all 10% bracket -> 1052.5 -> 1053
    assert r.line_16_tax == 1_053
    assert r.line_35a_refund == 3_147           # 4200 - 1053


def test_low_withholding_produces_amount_owed():
    w2 = W2(box1_wages=42_000, box2_federal_withholding=1_000)
    info = TaxpayerInfo(filing_status=T.SINGLE)
    r = compute_1040(w2, info)
    assert r.line_37_amount_owed == 1_915       # 2915 - 1000
    assert r.line_35a_refund == 0


def test_child_tax_credit_caps_at_tax():
    w2 = W2(box1_wages=42_000, box2_federal_withholding=4_200)
    info = TaxpayerInfo(filing_status=T.SINGLE, num_dependents=2)
    r = compute_1040(w2, info)
    # tax 2,915; 2 deps -> $4,400 CTC but capped at the tax owed
    assert r.line_19_ctc == 2_915
    assert r.line_22_tax_after_credits == 0
    assert r.line_35a_refund == 4_200  # all withholding refunded


def test_one_dependent_partial_credit():
    w2 = W2(box1_wages=42_000, box2_federal_withholding=4_200)
    info = TaxpayerInfo(filing_status=T.SINGLE, num_dependents=1)
    r = compute_1040(w2, info)
    assert r.line_19_ctc == 2_200            # one child, under the tax
    assert r.line_22_tax_after_credits == 715  # 2,915 - 2,200


def test_estimated_payments_added_to_total_payments():
    w2 = W2(box1_wages=42_000, box2_federal_withholding=4_200)
    info = TaxpayerInfo(filing_status=T.SINGLE, est_payments=1_500)
    r = compute_1040(w2, info)
    assert r.line_26_est_payments == 1_500
    assert r.line_33_total_payments == 5_700      # 4,200 + 1,500
    assert r.line_35a_refund == 2_785             # 5,700 - 2,915


def test_invalid_filing_status_rejected():
    with pytest.raises(ValueError):
        TaxpayerInfo(filing_status="bogus")


def test_negative_wages_rejected():
    with pytest.raises(Exception):
        W2(box1_wages=-5)
