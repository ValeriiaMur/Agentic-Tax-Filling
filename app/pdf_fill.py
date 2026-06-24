"""Fill the official IRS 2025 Form 1040 (AcroForm) with computed values.

Field names in the IRS PDF are generic (f1_47, f2_16, ...). The map below was
derived by inspecting the PDF's widget rectangles and matching them to the
printed line positions, then verified by reading values back in the tests. We
fill the *real* government form, so the download is a genuine 2025 Form 1040.
"""

from __future__ import annotations

import os
import re
from typing import Dict

from pypdf import PdfReader, PdfWriter

from . import tax_tables_2025 as T
from .schemas import Form1040Result, TaxpayerInfo, W2

_P1 = "topmostSubform[0].Page1[0]."
_P2 = "topmostSubform[0].Page2[0]."

# Logical name -> fully-qualified AcroForm field name.
FIELD_MAP: Dict[str, str] = {
    # identity (page 1) — field rects matched to the printed labels: the name
    # row sits below its labels at y~684, address at y~636, city/state/zip y~612.
    "first_name": _P1 + "f1_14[0]",
    "last_name": _P1 + "f1_15[0]",
    "ssn": _P1 + "f1_16[0]",
    "spouse_first": _P1 + "f1_17[0]",
    "spouse_last": _P1 + "f1_18[0]",
    "spouse_ssn": _P1 + "f1_19[0]",
    # address block lives under the Address_ReadOrder subform
    "address": _P1 + "Address_ReadOrder[0].f1_20[0]",
    "apt": _P1 + "Address_ReadOrder[0].f1_21[0]",
    "city": _P1 + "Address_ReadOrder[0].f1_22[0]",
    "state": _P1 + "Address_ReadOrder[0].f1_23[0]",
    "zip": _P1 + "Address_ReadOrder[0].f1_24[0]",
    # filing status radio + digital assets
    "filing_status_radio": _P1 + "c1_8[0]",
    "digital_assets_no": _P1 + "c1_10[1]",
    # income (page 1)
    "line_1a": _P1 + "f1_47[0]",
    "line_1z": _P1 + "f1_57[0]",
    "line_9_total_income": _P1 + "f1_73[0]",
    "line_11_agi": _P1 + "f1_75[0]",
    # tax & payments (page 2)
    "line_11b_agi": _P2 + "f2_01[0]",
    "line_12_std": _P2 + "f2_02[0]",
    "line_15_taxable": _P2 + "f2_06[0]",
    "line_16_tax": _P2 + "f2_08[0]",
    "line_18": _P2 + "f2_10[0]",
    "line_19_ctc": _P2 + "f2_11[0]",
    "line_22": _P2 + "f2_14[0]",
    "line_24_total_tax": _P2 + "f2_16[0]",
    "line_25a_wh": _P2 + "f2_17[0]",
    "line_25d_wh": _P2 + "f2_20[0]",
    "line_26_est": _P2 + "f2_21[0]",
    "line_33_payments": _P2 + "f2_29[0]",
    "line_34_overpaid": _P2 + "f2_30[0]",
    "line_35a_refund": _P2 + "f2_31[0]",
    "line_37_owed": _P2 + "f2_35[0]",
}

# Filing status -> radio export value on the c1_8 group.
_STATUS_EXPORT = {
    T.SINGLE: "/1",
    T.MFJ: "/2",
    T.MFS: "/3",
    T.HOH: "/4",
    T.QSS: "/5",
}

DEFAULT_TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "assets", "f1040_2025.pdf")


def _set_radio(writer, group_name: str, export: str) -> None:
    """Select an option by export value across a set of checkbox-style widgets.

    On this IRS form the filing-status and digital-asset choices are independent
    checkbox fields, each with its own single on-state (e.g. /1../5). We turn on
    exactly the widget whose appearance state matches `export` (setting both its
    /AS and its own field /V), and force every sibling in the group to /Off.
    """
    from pypdf.generic import NameObject

    target = NameObject(export)
    off = NameObject("/Off")
    for page in writer.pages:
        for annot in page.get("/Annots", []):
            obj = annot.get_object()
            if obj.get("/Subtype") != "/Widget":
                continue
            name = str(obj.get("/T") or "")
            parent = obj.get("/Parent")
            pname = str(parent.get_object().get("/T")) if parent else ""
            if group_name not in name and group_name not in pname:
                continue
            ap = obj.get("/AP")
            states = list(ap["/N"].keys()) if ap and "/N" in ap else []
            if export in states:
                obj[NameObject("/AS")] = target
                obj[NameObject("/V")] = target
            else:
                obj[NameObject("/AS")] = off
                obj[NameObject("/V")] = off


def _money(n: int) -> str:
    """IRS-style whole-dollar with thousands separators; blank for zero."""
    return f"{n:,}" if n else ""


def fill_1040(
    result: Form1040Result,
    info: TaxpayerInfo,
    w2: W2,
    output_path: str,
    template_path: str = DEFAULT_TEMPLATE,
) -> str:
    """Write a completed 2025 Form 1040 PDF and return its path."""
    reader = PdfReader(template_path)
    writer = PdfWriter()
    writer.append(reader)

    text_values = {
        FIELD_MAP["first_name"]: info.first_name,
        FIELD_MAP["last_name"]: info.last_name,
        # SSN box is a 9-cell comb field — digits only, no dashes.
        FIELD_MAP["ssn"]: re.sub(r"\D", "", info.ssn or ""),
        FIELD_MAP["address"]: info.address,
        FIELD_MAP["city"]: info.city,
        FIELD_MAP["state"]: info.state,
        FIELD_MAP["zip"]: info.zip_code,
        # income
        FIELD_MAP["line_1a"]: _money(result.line_1a_wages),
        FIELD_MAP["line_1z"]: _money(result.line_1z_total_wages),
        FIELD_MAP["line_9_total_income"]: _money(result.line_9_total_income),
        FIELD_MAP["line_11_agi"]: _money(result.line_11_agi),
        # page 2
        FIELD_MAP["line_11b_agi"]: _money(result.line_11_agi),
        FIELD_MAP["line_12_std"]: _money(result.line_12_standard_deduction),
        FIELD_MAP["line_15_taxable"]: _money(result.line_15_taxable_income),
        FIELD_MAP["line_16_tax"]: _money(result.line_16_tax),
        FIELD_MAP["line_18"]: _money(result.line_16_tax),
        FIELD_MAP["line_19_ctc"]: _money(result.line_19_ctc),
        FIELD_MAP["line_22"]: _money(result.line_22_tax_after_credits),
        FIELD_MAP["line_24_total_tax"]: _money(result.line_24_total_tax),
        FIELD_MAP["line_25a_wh"]: _money(result.line_25a_w2_withholding),
        FIELD_MAP["line_25d_wh"]: _money(result.line_25d_total_withholding),
        FIELD_MAP["line_26_est"]: _money(result.line_26_est_payments),
        FIELD_MAP["line_33_payments"]: _money(result.line_33_total_payments),
        FIELD_MAP["line_34_overpaid"]: _money(result.line_34_overpaid),
        FIELD_MAP["line_35a_refund"]: _money(result.line_35a_refund),
        FIELD_MAP["line_37_owed"]: _money(result.line_37_amount_owed),
    }

    if info.filing_status in (T.MFJ, T.MFS, T.QSS) and info.spouse_last_name:
        text_values[FIELD_MAP["spouse_first"]] = info.spouse_first_name
        text_values[FIELD_MAP["spouse_last"]] = info.spouse_last_name
        text_values[FIELD_MAP["spouse_ssn"]] = info.spouse_ssn

    for page in writer.pages:
        writer.update_page_form_field_values(page, text_values, auto_regenerate=False)

    # Radios (filing status, digital-assets "No") need direct widget handling:
    # set the matching widget's /AS and the group field's /V to the export value.
    _set_radio(writer, "c1_8", _STATUS_EXPORT[info.filing_status])
    _set_radio(writer, "c1_10", "/2")  # digital assets: No

    # Ensure viewers render the filled values.
    try:
        writer.set_need_appearances_writer(True)
    except Exception:
        pass

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as fh:
        writer.write(fh)
    return output_path
