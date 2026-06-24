# Agentic Tax-Filing Assistant — 2025 Form 1040

**▶ Live demo: <https://agentic-tax-filling.up.railway.app/>** — try it: drop in a
W-2 (or click *Use a sample W-2*), answer two short questions, and download the
completed 1040. The right-hand panel shows the agent's live decision trail.

A small **agentic harness** that helps a single-W-2 wage earner (~$40k) file a
U.S. federal **2025 Form 1040** through a warm, ≤5-question chat — and hands back
the completed, downloadable IRS PDF.

It's built to demonstrate four harness pillars, each enforced in code and visible
at runtime:

| Pillar | Where it lives | How it's enforced (not just "in the prompt") |
|---|---|---|
| **Chat loop** | `app/conversation.py`, `app/agent.py` | `TaxSession` carries W-2 data, filing status, the question budget, and the result across turns — one `message(text)` call per turn. A LangGraph pipeline runs the compute→fill tools. |
| **Tools** | `app/tools.py` | Real actions via a `ToolRegistry`: `extract_w2`, `compute_1040`, `fill_1040_pdf`. The last writes the official IRS PDF you download. |
| **Guardrails** | `app/guardrails.py` | Hard 5-question budget (`QuestionBudget`), scope/decline classifier, deterministic filing-status parsing, and W-2 validation — all in code. |
| **Observation** | `app/observability.py` | Every decision, tool call, result, and guardrail is emitted as a structured event, streamed to the UI's right-hand **Observation trail** and to logs. |

**Accuracy:** tax is computed in plain Python (`app/tax_engine.py`), never by the
LLM. The engine reproduces the official **IRS 2025 Tax Table** generation method
(tax the midpoint of each $50 row), verified to the dollar against the printed
table — e.g. taxable income $26,250 → Single **$2,915**, MFJ **$2,676**, HOH **$2,813**.

> Educational/hackathon demo with **fake data only**. Not tax advice, not a real
> filing, no e-filing.

---

## One-command local run

```bash
pip install -r requirements.txt && uvicorn app.server:app --reload --port 8000
```

Then open <http://localhost:8000>, drop in a W-2 (or click **Use a sample W-2**,
or just type `Box 1 wages 42000, Box 2 withholding 4200`), reply to the
filing-status and dependents questions in plain language, and download the
completed 1040. The right-hand panel shows the live observation trail.

No API key is required for the core flow (W-2 via paste/sample + full computation
+ PDF). Set `ANTHROPIC_API_KEY` to enable **Claude vision** for W-2 image/PDF
upload (`VISION_MODEL` defaults to `claude-haiku-4-5`).

### Run the tests

```bash
pip install -r requirements.txt pytest
pytest -q          # 57 tests: tax-table accuracy, CTC, guardrails, PDF fill, E2E
```

---

## Deploy (Railway)

1. Push this repo to GitHub.
2. In Railway: **New Project → Deploy from GitHub repo**, select it.
3. Railway auto-detects Python (`requirements.txt`) and uses `railway.json`'s
   start command (`uvicorn app.server:app --host 0.0.0.0 --port $PORT`).
4. (Optional) add `ANTHROPIC_API_KEY` in **Variables** to enable image upload.
5. Open the generated public URL. Health check: `/healthz`.

The same `Procfile` works on Render, Fly.io, or any host that injects `$PORT`.

---

## Interface

A deliberately **minimal web chat** (`static/index.html`, vanilla JS) — the brief
says UI polish isn't judged, so effort went to the harness. A single chat column
(drag-and-drop W-2, a "Use a sample W-2" link, and a free-text composer) with a
**live Observation trail** panel on the right that shows every phase, decision,
tool call, and guardrail as it happens. The browser holds no tax logic — every
figure comes from the backend.

## How it works

It's a natural free-text conversation, not a click-through of buttons. The user
types; the agent reads intent **deterministically in code** (negation-aware
affirmation, filing-status and dependent parsing), so the LLM never drives the
flow or computes a number.

```
await_w2 → confirm_w2 → filing_status → dependents → complete
                                              │
                                   [LangGraph] compute (compute_1040)
                                              └▶ finalize (fill_1040_pdf) → IRS PDF
```

Three core questions (confirm the W-2 figures · filing status · dependents) under
a hard 5-question budget — the two spare turns absorb a correction or a
clarification, and if the budget is hit the agent assumes a safe default and says
so rather than looping. Identity comes from the W-2; dependents apply the 2025
Child Tax Credit (capped at tax owed). After completion the user can still ask
about the result or change an answer, and the return recomputes.

## Project layout

```
app/
  tax_tables_2025.py  official 2025 constants (std deduction, brackets)
  tax_engine.py       deterministic computation + IRS Tax Table method
  schemas.py          typed W2 / TaxpayerInfo / Form1040Result (validation)
  guardrails.py       budget, scope, status parsing, W-2 validation
  w2_extract.py       Claude vision (haiku) + deterministic text/paste fallback
  pdf_fill.py         fills the official IRS f1040_2025.pdf by field map
  observability.py    structured per-session event trail + phased decision trail
  conversation.py     free-text TaxSession: deterministic turn policy + guardrails
  tools.py            ToolRegistry (observable real actions)
  agent.py            LangGraph compute→fill pipeline
  server.py           FastAPI: /api/session, /message, /w2, /sample, /observations, /download
static/index.html     minimal chat UI + live observation panel
assets/               official IRS PDFs + generated fake sample W-2
tests/                57 tests incl. IRS-verified tax values & full E2E
```

## Assets (official IRS tax-year 2025 forms)

- `assets/f1040_2025.pdf` — Form 1040 fillable PDF (the form we populate)
- `assets/i1040gi_2025.pdf` — 1040 instructions (the 2025 Tax Table used to verify the engine)
- `assets/fw2_2025.pdf` — blank W-2 reference
- `assets/sample_w2.png` / `sample_w2.json` — generated **fake** W-2 + ground truth

See `DECISIONS.md` for the key design choices and why.

## Security & privacy

What leaves the server for the LLM, and what doesn't:

- **Tax math, SSN, and address never reach the model.** All computation is
  deterministic Python; the SSN is captured server-side and written only into the
  downloaded PDF — it is never logged, never in the decision trail, and never sent
  to Anthropic.
- **Vision (W-2 upload) — SSN-minimized.** If a user uploads a W-2 image/PDF, the
  document is sent to Claude vision to read the figures. The prompt explicitly
  instructs the model **not to read or return the SSN**, and any SSN field is
  stripped from the response as a belt-and-suspenders step (`app/w2_extract.py`).
  The uploaded image itself still contains the SSN, so this path does transmit the
  document to Anthropic — paste/sample paths avoid that entirely.
- **Phrasing — name is masked.** The optional Claude phrasing layer
  (`app/humanize.py`) only rewrites the agent's outgoing sentences. Before any
  call, the taxpayer's name is replaced with a neutral placeholder and restored
  locally afterward, so **no name is transmitted** — only dollar amounts and the
  question wording. A post-check rejects any rewrite that alters a figure.
- **Prompt-injection safety.** W-2 content and user messages are treated as
  untrusted: tools return structured fields only, and tax math runs in code, so
  injected text can't change a computed number or the form.
- **Keys & data handling.** `ANTHROPIC_API_KEY` is read from the environment only
  (never committed/logged). Set `LLM_PHRASING=0` to disable model phrasing
  entirely, or omit the key to run fully offline (paste/sample + deterministic
  wording). Review Anthropic's API data-use policy for how uploaded content is
  handled on their side.

> This is a fake-data prototype — no real PII should be entered. The notes above
> describe the architecture for when real data would flow.

## Disclaimer

Educational/hackathon exercise only. Not tax advice, not for real filings, and
not for e-filing. Synthetic data only.
