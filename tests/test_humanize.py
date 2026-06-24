"""Spec for the Claude phrasing layer's guardrails (LLM path mocked-out via no key).

The number-preservation guard is the safety contract: a rewrite that drops or
changes a dollar amount must be rejected in favor of the deterministic text.
"""

import os

from app.humanize import _mask, _multiset_subset, humanize


def test_no_key_returns_original(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    msg = "Your tax is **$2,915** and your refund is $1,285."
    assert humanize(msg) == msg


def test_disabled_flag_returns_original(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_PHRASING", "0")
    msg = "Refund of $1,285."
    assert humanize(msg) == msg


def test_number_preservation_guard():
    # _multiset_subset operates on the lists of amounts extracted from each message
    assert _multiset_subset(["$2,915", "$1,285"], ["$2,915", "$1,285"])
    # a dropped amount fails the guard
    assert not _multiset_subset(["$2,915", "$1,285"], ["$2,915"])
    # a changed amount fails the guard
    assert not _multiset_subset(["$1,285"], ["$1,200"])


def test_empty_message_returns_original():
    assert humanize("") == ""


def test_name_is_masked_before_sending():
    msg = "Thanks, Jordan Rivera! I read **$42,000** in wages."
    masked, holders = _mask(msg, ["Jordan Rivera", "Jordan"])
    # the real name must not appear in what would be sent to the model
    assert "Jordan" not in masked
    assert "$42,000" in masked  # figures are untouched
    # and it restores exactly
    restored = masked
    for ph, term in holders.items():
        restored = restored.replace(ph, term)
    assert restored == msg


def test_vision_path_drops_ssn():
    from app.w2_extract import _coerce_vision_json
    raw = '{"employee_name":"A B","employee_ssn":"123-45-6789","box1_wages":42000}'
    data = _coerce_vision_json(raw)
    assert "employee_ssn" not in data and "ssn" not in data
    assert data["box1_wages"] == 42000.0
