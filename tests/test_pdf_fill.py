"""TDD spec for the 1040 PDF fill tool.

The contract: every dollar value written into a form field must equal the value
computed by the tax engine. We fill the real 2025 PDF, read the fields back, and
assert equality — so a mis-mapped field is caught automatically.
"""

import os

import pytest
from pypdf import PdfReader

from app.pdf_fill import FIELD_MAP, fill_1040
from app.schemas import TaxpayerInfo, W2
from app.tax_engine import compute_1040

ASSET = os.path.join(os.path.dirname(__file__), "..", "assets", "f1040_2025.pdf")

pytestmark = pytest.mark.skipif(
    not os.path.exists(ASSET), reason="official f1040_2025.pdf not present in assets/"
)


def _read_back(path):
    reader = PdfReader(path)
    fields = reader.get_fields()
    return {k: (v.get("/V") or "") for k, v in fields.items()}


def test_fill_writes_correct_money_lines(tmp_path):
    w2 = W2(box1_wages=42_000, box2_federal_withholding=4_200, employee_name="Jordan Rivera")
    info = TaxpayerInfo(
        filing_status="single", first_name="Jordan", last_name="Rivera",
        ssn="123-45-6789", address="100 Main St", city="Austin", state="TX", zip_code="78701",
    )
    result = compute_1040(w2, info)
    out = tmp_path / "out.pdf"

    fill_1040(result, info, w2, str(out))
    assert out.exists()

    vals = _read_back(str(out))
    # money lines reflect computed values, formatted with commas
    assert vals[FIELD_MAP["line_1a"]] == "42,000"
    assert vals[FIELD_MAP["line_11_agi"]] == "42,000"
    assert vals[FIELD_MAP["line_12_std"]] == "15,750"
    assert vals[FIELD_MAP["line_15_taxable"]] == "26,250"
    assert vals[FIELD_MAP["line_16_tax"]] == "2,915"
    assert vals[FIELD_MAP["line_24_total_tax"]] == "2,915"
    assert vals[FIELD_MAP["line_25a_wh"]] == "4,200"
    assert vals[FIELD_MAP["line_35a_refund"]] == "1,285"


def test_fill_sets_filing_status_radio(tmp_path):
    w2 = W2(box1_wages=42_000, box2_federal_withholding=4_200)
    info = TaxpayerInfo(filing_status="married_filing_jointly", first_name="A", last_name="B")
    result = compute_1040(w2, info)
    out = tmp_path / "mfj.pdf"
    fill_1040(result, info, w2, str(out))

    reader = PdfReader(str(out))
    fields = reader.get_fields()
    # filing status is a set of independent checkboxes; exactly one (export /2,
    # MFJ) must be on, and no other status export value may be selected.
    on_states = {str(v.get("/V")) for v in fields.values() if str(v.get("/V")) in
                 {"/1", "/2", "/3", "/4", "/5"}}
    assert on_states == {"/2"}
