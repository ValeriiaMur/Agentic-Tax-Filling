# Agent Rules — Agentic Tax-Filing Assistant

Conventions any agent (or human) working in this repo must follow. These are
enforced expectations, not suggestions.

## Test-Driven Development (red → green → refactor)

TDD is mandatory for all logic — especially the tax engine and PDF field mapping.

1. **Red** — write a failing test first. It must fail for the right reason (assert
   the real expected value, then watch it fail). Never write production code
   without a failing test demanding it.
2. **Green** — write the *minimum* code to make the test pass. No extra
   features, no speculative generality.
3. **Refactor** — clean up with the test green. Tests stay green throughout.

Rules:
- One behavior per test; name tests for the behavior (`test_single_filer_40k_tax_matches_table`).
- For the tax engine, every golden case is **hand-verified from the IRS 2025
  worksheet/Tax Table** and asserted as **exact integer-dollar equality** — never
  approximate, never "close enough."
- A bug fix starts with a failing test that reproduces the bug.
- Run the full suite before every commit: `pytest`. Don't commit red.

## Determinism & correctness (non-negotiable)

- **Tax math lives in code, never in the LLM.** The model gathers inputs and
  talks; it must never compute or assert a tax figure.
- At ~$40k, use the **2025 Tax Table lookup** (rounded $50-row method), not the
  continuous bracket formula — they differ by a few dollars and the IRS expects
  the table.
- All 2025 parameters live in `app/tax_tables_2025.py` — the single source of
  truth. Don't hardcode tax constants anywhere else.
- Every number written to the PDF must come from the deterministic engine and
  equal the computed value (assert this in tests).

## The four pillars must stay real

Changes must keep each pillar **enforced and visible**, not cosmetic:
- **Chat / Loop** — state carried across turns in LangGraph.
- **Tools** — typed schemas (Pydantic); each tool returns typed success/failure.
- **Guardrails** — ≤5-question budget enforced in state (hard stop); scope/refusal
  rules; W-2 validation with structured-form fallback.
- **Observability** — every decision, tool call (with I/O), and computed line value
  is emitted as a **structured event** by the code that runs it (not a log string),
  surfaced in the UI.

## Scope & safety

- **Tax year 2025 only.** No other years.
- **Fake/synthetic test data only.** No real PII, no real filings, no e-filing.
- This is an **educational prototype** — the agent must never present itself as
  giving tax advice. Out-of-scope asks (multiple W-2s, itemizing, non-W-2 income,
  real advice) → decline gracefully.
- **Keep it simple.** Resist scope creep — a working, well-architected harness
  beats breadth of features. Don't add a dependency or abstraction a test doesn't
  demand.

## Code conventions

- Python, type-hinted. Validate external/tool boundaries with Pydantic.
- Pure functions for tax logic (easy to test); side effects (PDF write, model
  calls) at the edges.
- Secrets (`ANTHROPIC_API_KEY`, etc.) via environment variables only — never in
  the repo, never logged.
- Treat W-2 content and user messages as **untrusted input** (prompt-injection
  safe): tools return structured fields only; injected text can't alter computed
  numbers or tool behavior.
- Small, focused commits with clear messages. Don't commit generated artifacts or
  the contents of `assets/` changes without reason.
