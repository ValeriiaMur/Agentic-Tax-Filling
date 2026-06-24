"""Official IRS tax-year 2025 federal parameters.

Single source of truth for every number the tax engine uses. Values verified
against the 2025 Form 1040 (standard deduction amounts printed on the form) and
the IRS 2025 inflation-adjustment revenue procedure (Rev. Proc. 2024-40).

Keeping these as plain data — not buried in code — is deliberate: a reviewer can
audit the constants in one place, and the tax year is the only date-bound
dependency in the whole project.
"""

from __future__ import annotations

TAX_YEAR = 2025

# Filing status codes used throughout the app.
SINGLE = "single"
MFJ = "married_filing_jointly"
MFS = "married_filing_separately"
HOH = "head_of_household"
QSS = "qualifying_surviving_spouse"

FILING_STATUSES = [SINGLE, MFJ, MFS, HOH, QSS]

FILING_STATUS_LABELS = {
    SINGLE: "Single",
    MFJ: "Married filing jointly",
    MFS: "Married filing separately",
    HOH: "Head of household",
    QSS: "Qualifying surviving spouse",
}

# 2025 standard deduction by filing status (printed on the 2025 Form 1040, line 12).
STANDARD_DEDUCTION = {
    SINGLE: 15_750,
    MFS: 15_750,
    MFJ: 31_500,
    QSS: 31_500,
    HOH: 23_625,
}

# 2025 ordinary-income tax brackets (Rev. Proc. 2024-40).
# Each entry: (lower_bound_inclusive, marginal_rate). Bounds ascending.
BRACKETS = {
    SINGLE: [
        (0, 0.10),
        (11_925, 0.12),
        (48_475, 0.22),
        (103_350, 0.24),
        (197_300, 0.32),
        (250_525, 0.35),
        (626_350, 0.37),
    ],
    MFS: [
        (0, 0.10),
        (11_925, 0.12),
        (48_475, 0.22),
        (103_350, 0.24),
        (197_300, 0.32),
        (250_525, 0.35),
        (375_800, 0.37),
    ],
    MFJ: [
        (0, 0.10),
        (23_850, 0.12),
        (96_950, 0.22),
        (206_700, 0.24),
        (394_600, 0.32),
        (501_050, 0.35),
        (751_600, 0.37),
    ],
    QSS: [
        (0, 0.10),
        (23_850, 0.12),
        (96_950, 0.22),
        (206_700, 0.24),
        (394_600, 0.32),
        (501_050, 0.35),
        (751_600, 0.37),
    ],
    HOH: [
        (0, 0.10),
        (17_000, 0.12),
        (64_850, 0.22),
        (103_350, 0.24),
        (197_300, 0.32),
        (250_525, 0.35),
        (626_350, 0.37),
    ],
}

# The IRS Tax Table is used for taxable income below this threshold; above it, the
# Tax Computation Worksheet (continuous bracket formula) applies.
TAX_TABLE_CEILING = 100_000

# 2025 Child Tax Credit per qualifying child (simplified; capped at tax owed).
CHILD_TAX_CREDIT = 2_200
