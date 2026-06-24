"""TDD spec for the W-2 text/paste parser (the deterministic fallback path).

The vision path (Claude) is wired separately and exercised at runtime; here we
lock the offline parser that powers the structured-form / paste fallback so the
system works end-to-end without a live LLM key.
"""

from app.w2_extract import parse_w2_text


def test_parse_labelled_boxes():
    text = """
    Employee: Jordan Rivera
    Box 1 Wages, tips, other compensation: 42,000.00
    Box 2 Federal income tax withheld: 4,200.00
    """
    data = parse_w2_text(text)
    assert data["box1_wages"] == 42000.0
    assert data["box2_federal_withholding"] == 4200.0
    assert "Jordan Rivera" in data.get("employee_name", "")


def test_parse_plain_numbers_with_keywords():
    text = "wages 38500 federal withholding 3100"
    data = parse_w2_text(text)
    assert data["box1_wages"] == 38500.0
    assert data["box2_federal_withholding"] == 3100.0


def test_parse_missing_withholding_defaults_zero():
    text = "Box 1 wages: 40000"
    data = parse_w2_text(text)
    assert data["box1_wages"] == 40000.0
    assert data["box2_federal_withholding"] == 0.0


def test_parse_no_wages_returns_none_wages():
    data = parse_w2_text("hello there")
    assert data.get("box1_wages") is None
