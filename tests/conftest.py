"""Test-wide defaults.

The deterministic policy (conversation.py) owns *what* the agent says and every
number; `humanize` is a cosmetic, temperature-1.0 LLM rewrite layered on top.
Tests assert the policy's exact wording, so the suite must run against the
deterministic templates — not a non-deterministic paraphrase that varies run to
run and only appears when an ANTHROPIC_API_KEY happens to be present (e.g. via a
local .env). Pinning LLM_PHRASING=0 keeps tests deterministic and fully offline.

Individual tests that need the phrasing layer's own behavior set the env
themselves via monkeypatch (function-scoped), which overrides this default and
is restored afterward.
"""

import os

os.environ.setdefault("LLM_PHRASING", "0")
