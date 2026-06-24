# Agentic Tax-Filing Assistant — 2025 Form 1040

A small **agentic harness** that helps a single-W-2 wage earner (~$40k) file a
U.S. federal **2025 Form 1040** through a warm, ≤5-question chat — and hands back
the completed, downloadable IRS PDF.

It's built to demonstrate four harness pillars, each enforced in code and visible
at runtime:

| Pillar | Where it lives | How it's enforced (not just "in the prompt") |
|---|---|---|
| **Chat loop** | `app/agent.py`, `app/conversation.py` | A LangGraph state machine runs once per user turn; `SessionState` carries W-2 data, filing status, the question budget, and the result across turns. |
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

Then open <http://localhost:8000>, click **sample W-2** (or paste
`Box 1 wages 42000, Box 2 withholding 4200`), answer the filing-status and
dependents questions, and download the completed 1040.

No API key is required for the core flow (W-2 via paste/form + full computation +
PDF). Set `ANTHROPIC_API_KEY` to enable **Claude vision** for W-2 image/PDF upload
and (optionally, `USE_LLM_PHRASING=1`) warm rephrasing.

### Run the tests

```bash
pip install -r requirements.txt pytest
pytest -q          # 56 tests: tax-table accuracy, CTC/est, guardrails, PDF fill, E2E
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

## Interface — Malleable UI

The front end (`static/index.html`, vanilla JS) is a 1:1 build of the **Malleable
UI** design: a near-white surface, a single iris accent, an ambient canvas "blob"
that breathes per stage, spring-based "crystallize" motion, and a **Decision
Trail** drawer that exposes every observation, rule, calculation, and guardrail
the agent used. Every figure shown — W-2 boxes, the five questions, the computed
1040, the trail — is fetched from the backend; nothing is hardcoded in the browser.

## How it works

```
idle → upload → processing → confirm → questions×5 → processing → review → download

last answer ─▶ [LangGraph]  compute (compute_1040) ─▶ finalize (fill_1040_pdf)
                                                         → downloadable IRS PDF
```

Five plain-language questions (filing status · dependents · other income ·
deduction · estimated payments) — the hard ceiling. Identity comes from the W-2.
Dependents apply the 2025 Child Tax Credit (capped at tax owed); estimated
payments add to line 26; choosing "itemized" or declaring non-W-2 income each
logs a guardrail and the agent explains the fallback. A blurry-photo path flags
Box 1 for human verification before proceeding.

## Project layout

```
app/
  tax_tables_2025.py  official 2025 constants (std deduction, brackets)
  tax_engine.py       deterministic computation + IRS Tax Table method
  schemas.py          typed W2 / TaxpayerInfo / Form1040Result (validation)
  guardrails.py       budget, scope, status parsing, W-2 validation
  w2_extract.py       Claude vision + deterministic text/paste fallback
  pdf_fill.py         fills the official IRS f1040_2025.pdf by field map
  observability.py    structured per-session event trail
  conversation.py     deterministic turn policy (the agent's decisions)
  tools.py            ToolRegistry (observable real actions)
  agent.py            LangGraph harness wiring the four pillars
  server.py           FastAPI: chat, upload, events, download
static/index.html     minimal chat UI + live observation panel
assets/               official IRS PDFs + generated fake sample W-2
tests/                50 tests incl. IRS-verified tax values & full E2E
```

## Assets (official IRS tax-year 2025 forms)

- `assets/f1040_2025.pdf` — Form 1040 fillable PDF (the form we populate)
- `assets/i1040gi_2025.pdf` — 1040 instructions (the 2025 Tax Table used to verify the engine)
- `assets/fw2_2025.pdf` — blank W-2 reference
- `assets/sample_w2.png` / `sample_w2.json` — generated **fake** W-2 + ground truth

See `DECISIONS.md` for the key design choices and why.

## Disclaimer

Educational/hackathon exercise only. Not tax advice, not for real filings, and
not for e-filing. Synthetic data only.
