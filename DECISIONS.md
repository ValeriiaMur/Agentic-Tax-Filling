# DECISIONS

Key choices for the open items, and why. (Educational prototype — fake data only.)

**Language & framework — Python + FastAPI + LangGraph.** LangGraph's explicit
state graph makes two pillars legible in code: the *chat loop* (a compiled graph
invoked once per turn) and *state* (`SessionState` carried across turns). FastAPI
gives a tiny, dependency-light web server. The front end is intentionally minimal
(one HTML file) — effort went to the harness, not UI polish.

**LLM — Anthropic Claude, and deliberately optional.** Claude does two jobs:
W-2 **vision** extraction and (opt-in) **warm rephrasing**. It never decides flow
and never computes a number. The conversation policy and tax math are
deterministic, so the whole system runs correctly and is fully testable **without
an API key** — the key only unlocks image upload and tone polish. This keeps the
demo robust for a judge and keeps cost negligible.

**Tax computation — deterministic, and verified to the dollar.** `tax_engine.py`
computes everything in plain Python from bundled official 2025 parameters
(`tax_tables_2025.py`). For incomes under $100k it reproduces the **IRS Tax Table
generation method** (tax the midpoint of each $50 row, round half up); above
$100k it uses the Tax Computation Worksheet formula. I verified the output
against the printed 2025 Tax Table in the IRS instructions across multiple rows
and filing statuses (e.g. $26,250 → Single 2,915 / MFJ 2,676 / HOH 2,813 — exact
matches). Accuracy is a top priority, so this is locked by golden unit tests.

**The 1040 — fill the real government PDF.** I populate the official IRS
`f1040_2025.pdf` AcroForm. Its fields are generically named (`f1_47`, `f2_16`…),
so I derived a field map from the widget rectangle positions and **verified it by
reading values back** in tests. Filing status turned out to be five independent
checkbox widgets (export values /1–/5), handled directly. The download is a
genuine 2025 Form 1040.

**W-2 input — vision with a deterministic fallback.** Upload an image/PDF (Claude
vision) *or* paste/type the box values (regex parser). The parser is the offline
guarantee that the system works end-to-end without a key, and the fallback path
also catches messy vision output. All extracted data is validated before it can
reach the engine or the form.

**Guardrails — enforced in code, not the prompt.** (1) A hard **5-question
budget** counted in `QuestionBudget` on every turn. (2) A **scope classifier**
that declines investing/tax-advice/off-task asks *without* spending a question.
(3) **Deterministic filing-status parsing** so the form's status is never guessed
by the LLM. (4) **W-2 validation** (wages required, withholding-over-wages
flagged, etc.) with a graceful retry. Pydantic models validate at every boundary.

**Conversation design — free-text, 3 core questions, warm tone.** It's a natural
typed conversation, not a click-through of buttons (the brief explicitly wants
"warm and human, not robotic or interrogative"). Identity comes from the W-2, so
after confirming the figures the agent asks just two more: filing status →
dependents. Intent is parsed **deterministically in code** — negation-aware
affirmation ("no, that's not right" reads as a NO even though it contains
"right"), filing-status, and dependent-count parsing — so the LLM never drives
the flow. The 5-question budget is a hard ceiling counted in code; the two spare
turns absorb a correction or clarification, and when the budget is exhausted the
agent assumes a safe default and says so rather than looping. After completion
the user can ask about the result or change an answer, and it recomputes.

**Frontend — deliberately minimal.** `static/index.html` (vanilla JS, no build
step) is a single chat column with drag-and-drop W-2 upload, a "Use a sample W-2"
link, a free-text composer, and a live Observation-trail panel on the right. The
brief says UI polish isn't judged, so effort went to the harness. The browser
holds no tax logic — W-2 figures, the computed 1040, and the trail all come from
the backend.

**State & sessions — in-memory per session.** A `dict` of `session_id → TaxSession`.
Simplest thing that demonstrates the loop for a single-instance prototype; a
production build would use a shared store. PDFs are written to an output dir.

**Observation — structured events, surfaced in the UI.** Every decision, tool
call (with I/O), result, and guardrail firing is emitted to a per-session
`ObservationLog` and shown live in the right-hand panel of the chat, not just in
logs. Because events come from the code that actually runs the tools, the trail
can't drift from reality. (LangSmith tracing can be layered on via env vars.)

**Hosting — Railway** (free, Git-push deploy). `railway.json` + `Procfile` bind
to `$PORT`; the same setup runs on Render/Fly. Health check at `/healthz`.

**Testing — 57 tests, TDD.** Tax-table accuracy (official IRS values), Child Tax
Credit math, guardrails, PDF field round-trip, and full session **end-to-end**
tests (sample W-2 in → downloadable 1040 out) that run offline with no LLM key.

## Documented limitations (scope, on purpose)

- Single W-2; wage income + federal withholding only. No EIC, no itemizing, no
  non-W-2 income — correct for the target profile.
- Dependents apply the 2025 Child Tax Credit ($2,200/child, capped at tax owed).
  Filing status is selectable (single, MFJ, MFS, HOH, QSS) and changes the
  deduction/brackets. (The engine also supports estimated payments; the current
  3-question flow doesn't ask for them, so they default to zero.)
- Tax is computed with the IRS 2025 Tax Table (more accurate than a raw bracket
  formula for incomes under $100k); a few dollars may differ from a continuous-
  bracket estimate, by design.
- In-memory state means sessions reset on redeploy — fine for a demo.
