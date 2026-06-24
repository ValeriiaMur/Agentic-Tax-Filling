# Agentic Tax-Filing Assistant

A small agentic system that helps a person file a U.S. federal income tax return
(**2025 Form 1040**) by chatting with them. A user shows up with a single W-2
(~$40,000/year), has a short, friendly conversation, and walks away with a
completed 2025 Form 1040 they can download.

Built for a hackathon challenge. This is an **educational prototype**, not tax
advice — it uses **fake test data only**, performs no e-filing, and handles no
real PII.

## The four pillars

Every harness has the same four responsibilities. Here's how each one is realized
in this project:

| Pillar            | Responsibility                                          | How it's realized here                                                                 |
| ----------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| **Chat / Loop**   | Drives reasoning across turns until the task is done.   | LangGraph cyclic graph carrying per-session state (extracted W-2 fields, filing status, answers, question count) across turns until the 1040 is complete. |
| **Tools**         | Lets the model read data and change the outside world.  | Typed tools: `extract_w2` (reads the W-2), `compute_1040` (deterministic tax engine), `fill_1040_pdf` (writes the downloadable return). |
| **Guardrails**    | Constrains inputs, outputs, and actions to safe bounds. | ≤5-question budget enforced in state; deterministic tax math kept outside the model; scope/refusal rules (no tax advice, no out-of-scope filings); W-2 validation with structured-form fallback. |
| **Observability** | Records what happened so you can debug and improve.     | In-app, judge-visible trail of every decision, tool call (with I/O), and computed 1040 line value — surfaced in the UI, not just logs; mirrored to LangSmith. |

## Stack

- **Backend:** Python, FastAPI, LangGraph
- **Model:** Anthropic Claude (conversation + W-2 vision extraction)
- **Tax math:** deterministic engine using bundled 2025 IRS parameters (never the LLM)
- **PDF:** official 2025 IRS fillable Form 1040, populated via `pypdf` / `reportlab`

## Project layout

```
.
├── app/                  # Application code
│   ├── tax_tables_2025.py  # 2025 federal parameters (single source of truth)
│   └── ...
├── assets/               # Official IRS tax-year 2025 forms (see below)
├── docs/                 # Challenge brief & pre-search notes
│   ├── requirements.md
│   └── tax_filing_agent_presearch.md
├── requirements.txt
└── README.md
```

## Assets

Official IRS **tax year 2025** forms, downloaded from irs.gov:

- `assets/f1040_2025.pdf` — 2025 Form 1040 (fillable PDF, the form we populate)
- `assets/i1040gi_2025.pdf` — 2025 Form 1040 instructions (includes the 2025 Tax Table and standard deduction figures used to verify the engine)
- `assets/fw2_2025.pdf` — 2025 Form W-2 (reference for building the realistic fake test W-2)

## Local run

```bash
pip install -r requirements.txt
# set your model key
export ANTHROPIC_API_KEY=...
uvicorn app.main:app --reload
```

Then open the chat in your browser.

## Disclaimer

Educational/hackathon exercise only. Not tax advice, not for real filings, and
not for e-filing. Test with synthetic data only.
