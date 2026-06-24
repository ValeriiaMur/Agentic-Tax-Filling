# Pre-Search Checklist — Agentic Tax-Filing Assistant

*Complete this before writing code. Save your AI conversation as a reference document.*

**Project:** Agentic Tax-Filing Assistant (Hackathon Challenge — fill a 2025 Form 1040 from a single ~$40k W-2 via chat)
**Prepared by:** val
**Date:** 2026-06-24

**Legend:** plain text = cited from the brief · *Inferred:* = defensible inference · *Out of scope* = ruled out by context · **Not specified** = explicit gap to confirm

> **Owner-flagged top priorities:** **Accuracy** (§9 Eval, §10 Verification — deterministic engine + exact-match golden tests using the 2025 Tax Table) and **Observability** (§8 — enforced structured event trail, visible in-app and mirrored to LangSmith). The vision provider is **Claude** (primary), with OpenAI named as the low-risk fallback.

---

## Phase 1: Define Your Constraints

### 1. Domain Selection

- **Which domain: healthcare, insurance, finance, legal, or custom?**
  Finance — specifically U.S. personal income tax preparation. Custom-narrow: a single tax year (2025) and a single artifact (IRS Form 1040).
- **What specific use cases will you support?**
  One core flow: a W-2 wage earner (~$40,000/yr) chats with the agent, supplies a W-2, answers ≤5 questions, and downloads a completed 2025 Form 1040. Filing status must be variable (single, married filing jointly, etc.). Stretch: a dependent, or correcting an answer mid-conversation.
- **What are the verification requirements for this domain?**
  Tax math must be computed deterministically, not by the LLM, and must reconcile against the 2025 standard deduction, tax tables/brackets, and W-2 withholding. The 1040 is explicitly an educational prototype, not tax advice and not an e-filing — the agent must not present itself as giving tax advice.
- **What data sources will you need access to?**
  The 2025 IRS Form 1040 (fillable PDF) and 2025 federal parameters: standard deduction amounts by filing status, tax brackets/tax tables, and any relevant constants. The W-2 itself is the per-user data source, supplied at runtime. *Inferred:* parameters hardcoded as a small versioned table rather than fetched live, since only tax year 2025 is in scope.

### 2. Scale & Performance

- **Expected query volume?**
  Prototype / demo scale — judges trying it end-to-end. *Inferred:* low tens of concurrent sessions at most; no production traffic.
- **Acceptable latency for responses?**
  *Inferred:* interactive chat, sub-3s per turn is the target; the only heavier step is W-2 vision extraction and PDF generation, where a few seconds is acceptable with a visible "working" state.
- **Concurrent user requirements?**
  *Inferred:* a handful of simultaneous judge sessions; per-session state must be isolated. No horizontal-scale requirement.
- **Cost constraints for LLM calls?**
  Must run on free hosting (Railway free tier) and free/low-cost model usage. *Inferred:* keep to a small number of Claude calls per session (extraction + conversation turns); budget is "free-tier friendly," exact $/session **Not specified — confirm acceptable spend with project owner.**

### 3. Reliability Requirements

- **What's the cost of a wrong answer in your domain?**
  In real tax filing, high (misfiling, penalties) — but here it is a prototype with fake data only, no real PII and no real filings, so live blast radius is contained. Reputationally for judging, a wrong line on the 1040 is the primary failure: correctness of the produced form is a top judging criterion.
- **What verification is non-negotiable?**
  Deterministic tax computation in code (not the model); validation that W-2 numbers are present and sane before filling; the produced PDF must reflect exactly the computed values. End-to-end must actually work, not mock a single happy-path step.
- **Human-in-the-loop requirements?**
  The user is the human in the loop: the agent should confirm the key extracted W-2 figures and the chosen filing status back to the user before producing the form. *Inferred:* a brief "here's what I've got, look right?" confirmation rather than blind auto-fill.
- **Audit/compliance needs?**
  No real compliance regime (educational, no e-filing). The relevant "audit" need is the **Observation pillar**: a visible trail of decisions, tool calls, and computed values a judge can inspect. *Out of scope* — formal regulatory audit/retention.

### 4. Team & Skill Constraints

- **Familiarity with agent frameworks?**
  Building on LangGraph (chosen stack). *Inferred:* comfortable enough with Python agent loops to expose the four pillars explicitly in code; LangGraph chosen partly because its graph + state model makes the chat loop and state pillar legible.
- **Experience with your chosen domain?**
  *Inferred:* working knowledge of Form 1040 basics (W-2 wages, standard deduction, withholding, refund/owed) sufficient for the single-W-2 scenario; deeper tax edge cases are out of scope by design.
- **Comfort with eval/testing frameworks?**
  *Inferred:* comfortable with pytest-style unit tests for the deterministic tax engine and tool layer; lighter on formal LLM eval harnesses. Testing strategy leans on golden-case fixtures (see §9, §13).

---

## Phase 2: Architecture Discovery

### 5. Agent Framework Selection

- **LangChain vs LangGraph vs CrewAI vs custom?**
  LangGraph. Its explicit state graph cleanly demonstrates two required pillars: the **chat loop** (graph cycles carrying state across turns) and **state management**.
- **Single agent or multi-agent architecture?**
  Single agent. *Inferred:* the task is narrow (extract → ask → compute → fill); a multi-agent split would add complexity without benefit and works against the "keep it simple" rule.
- **State management requirements?**
  Conversation state must persist across turns: extracted W-2 fields, filing status, answers collected so far, question count (to enforce the ≤5 budget), and a running observation/decision log. Held in LangGraph state keyed per session. *Inferred:* in-memory per-session store is sufficient for a prototype; no database required.
- **Tool integration complexity?**
  Low-to-moderate. A small fixed tool set (W-2 extraction, tax computation, PDF fill) with typed schemas. The tools, not the prose, are where the **Tools pillar** is demonstrated — at minimum the one that produces the filled return.

### 6. LLM Selection

- **GPT-5 vs Claude vs open source?**
  Anthropic Claude (e.g. a Sonnet-class model) for conversation and W-2 vision extraction — chosen for strong tool calling and warm, human tone (conversation quality is explicitly judged).
- **Function calling support requirements?**
  Required: the agent must invoke typed tools (extract, compute, fill-PDF). Claude's tool use covers this. Tax math is deliberately kept out of the model and done in code.
- **Vision provider for W-2 extraction (fallback plan):**
  Primary: Claude vision (same provider/key as the conversation — simplest). If Claude vision is unavailable, the easiest drop-in is **OpenAI GPT-4o / 4o-mini vision** (one extra API key, well-documented image input). **OpenRouter** is the alternative if model-swapping without code changes is wanted (single key, many models behind it) — slightly more setup. Provider choice is low-risk because a misread never reaches the form: the structured-form fallback, deterministic engine, and user confirmation all catch bad extractions before the 1040 is filled. *Recommendation:* Claude → OpenAI as the named fallback.
- **Context window needs?**
  Small. A single W-2, a short ≤5-question conversation, and a compact system prompt fit comfortably; no long-context requirement.
- **Cost per query acceptable?**
  Must stay free-tier friendly. *Inferred:* a few model calls per session (one vision extraction + a handful of chat turns) keeps cost negligible. Exact per-session ceiling **Not specified — confirm with project owner.**

### 7. Tool Design

- **What tools does your agent need?**
  At minimum: (1) `extract_w2` — vision/parse a W-2 into structured fields; (2) `compute_1040` — deterministic tax engine (wages → AGI → taxable income → tax → refund/owed) using 2025 parameters; (3) `fill_1040_pdf` — populate the official 2025 fillable PDF and return a downloadable file. *Inferred:* a `validate_w2` check may be folded into extraction.
- **External API dependencies?**
  Anthropic API for the model. The 2025 1040 PDF and tax parameter table are bundled locally, not fetched live. No external tax-calculation API.
- **Mock vs real data for development?**
  Real official 2025 1040 form; **fake/test W-2 data only** (a realistic synthetic W-2 supplied for testing). No real PII, ever.
- **Error handling per tool?**
  Each tool returns typed success/failure. Extraction failures or missing boxes fall back to the structured form input (W-2 input = vision with form fallback). Compute validates inputs and refuses to run on impossible values; PDF fill verifies all required fields are present before writing.

### 8. Observability Strategy — *PRIORITY*

> Flagged by the owner as a top priority. Observability is one of the four judged pillars and must be **enforced and visible, not "in the prompt."**

- **LangSmith vs Braintrust vs other?**
  Two layers, both planned: (1) **LangSmith** for full trace capture (every node, model call, and tool I/O) — pairs natively with LangGraph and gives a judge a deep timeline. (2) An **in-app, judge-visible observation panel** rendered in the UI (the stretch goal made core here): a live, human-readable trail of each decision, every tool call with its inputs/outputs, and — critically — every computed 1040 line value with the parameter it used. The UI panel is the primary demo artifact; LangSmith is the deep backstop.
- **What metrics matter most?**
  Per session: question count vs the ≤5 budget (with a hard stop), every tool call's success/failure, each computed line value vs the golden-expected value, the W-2 extraction confidence and whether fallback fired, and end-to-end completion (W-2 in → downloadable 1040 out). Each metric is emitted as a structured event, not just a log line.
- **Real-time monitoring needs?**
  The in-app trail updates live during the conversation so a judge watches decisions as they happen. *Inferred:* no external alerting/on-call needed at demo scale.
- **Cost tracking requirements?**
  A per-session token/cost counter is included (cheap to add, proves free-tier viability and adds to the observability story). Exposed in the same observation panel.
- **Implementation note (enforcement):**
  Observation is implemented as a structured event log written by the agent/tool layer (append-only per session in state), then both (a) streamed to the UI panel and (b) mirrored to LangSmith. Because the events are emitted by the code that actually runs the tools and computes the math, the trail cannot drift from what the agent really did.

### 9. Eval Approach — *PRIORITY (accuracy)*

> Flagged by the owner as a top priority. Correctness of the produced 1040 is a top judged criterion, so accuracy is enforced by deterministic computation + golden tests, never by trusting the model.

- **How will you measure correctness?**
  Golden test cases: fixed W-2 + filing-status inputs with hand-verified expected 1040 line values (line 1 wages, AGI, standard deduction, taxable income, tax, withholding/line 25, refund/amount owed). The deterministic engine must match every line **exactly** (integer-dollar equality, not approximate). Each golden case is computed by hand from the IRS worksheet, then frozen as the assertion.
- **Ground truth data sources?**
  2025 IRS standard deduction by filing status, the 2025 tax brackets, and the **2025 Tax Table** for taxable incomes under $100k (the ~$40k case falls in the table, which uses $50 bracket rows — the engine must use the table, not the raw bracket formula, to match the IRS to the dollar). Manual worksheet calculations anchor each case.
- **Tax-table vs formula accuracy note:**
  At ~$40k the IRS requires the Tax Table (rounded $50-row midpoint method), which differs from the continuous bracket formula by a few dollars. The engine implements the table lookup for in-table incomes so the output reconciles exactly with what the IRS expects — this is a known accuracy trap and is called out deliberately.
- **Automated vs human evaluation?**
  Automated unit/golden tests for the tax engine and PDF field mapping (assert the value written to each PDF field equals the computed value); human spot-check of conversation tone and the final rendered PDF.
- **CI integration for eval runs?**
  Run pytest on every push (Railway deploy gated on green tests). Lightweight but real, since accuracy is the bar.

### 10. Verification Design

- **What claims must be verified?**
  Every number written to the 1040 must come from the deterministic engine, and the engine's inputs must match the confirmed W-2 figures and filing status. The agent must never assert a tax figure it didn't compute in code.
- **Fact-checking data sources?**
  The bundled 2025 parameter table is the single source of truth for deductions and brackets. Cross-checked against IRS published 2025 figures during development.
- **Confidence thresholds?**
  W-2 vision extraction below a confidence/completeness bar triggers the structured-form fallback rather than guessing, and the agent always echoes the extracted figures back for user confirmation before computing — so no number reaches the form unverified. Exact threshold set empirically during testing.
- **Escalation triggers?**
  Missing/contradictory W-2 data, out-of-scope requests (multiple W-2s, itemizing, non-W-2 income), or anything resembling a request for real tax advice → the agent declines gracefully and stays within the educational prototype boundary (a **Guardrail**).

---

## Phase 3: Post-Stack Refinement

### 11. Failure Mode Analysis

- **What happens when tools fail?**
  Vision extraction failure → fall back to structured W-2 form entry. Compute failure (bad inputs) → ask the user to re-confirm the specific box. PDF fill failure → surface a clear error and retry rather than handing over a partial form.
- **How to handle ambiguous queries?**
  Stay on-task: the agent steers back to the ≤5 needed questions. Ambiguous filing-status answers get one clarifying confirmation rather than an open-ended exchange (mindful of the question budget).
- **Rate limiting and fallback strategies?**
  *Inferred:* minimal at prototype scale; on model rate-limit, retry with backoff and show a "one sec" state. The deterministic engine and PDF step have no external rate limits.
- **Graceful degradation approach?**
  If vision is down entirely, the form-entry path still produces a correct 1040 — the core promise (real form out) never depends solely on the LLM.

### 12. Security Considerations

- **Prompt injection prevention?**
  Treat W-2 content and user messages as untrusted: extraction returns structured fields only, and tax math runs in code, so injected text cannot alter computed numbers or tool behavior. System prompt fixes scope and refuses tax-advice / out-of-scope asks (a **Guardrail**).
- **Data leakage risks?**
  **Fake test data only** — no real PII by rule. *Inferred:* per-session state is in-memory and not persisted/shared across sessions; nothing logged should contain real taxpayer identifiers.
- **API key management?**
  Anthropic key via environment variables / Railway secrets, never in the repo. *Inferred:* standard env-var handling.
- **Audit logging requirements?**
  No regulatory logging. The observation trail (decisions, tool calls, computed values) doubles as the demo's audit view; it should avoid storing sensitive content beyond the synthetic test data.

### 13. Testing Strategy

- **Unit tests for tools?**
  Yes — the deterministic tax engine (per filing status, the ~$40k case and boundaries) and the PDF field-mapping layer get unit tests with hand-verified expected values.
- **Integration tests for agent flows?**
  A scripted end-to-end test: supply the fake W-2 → run the conversation → assert a downloadable 1040 with correct line values. Proves the "actually works end-to-end" bar.
- **Adversarial testing approach?**
  Messy/partial W-2 input (missing boxes, low-quality image) to confirm the form-fallback path; out-of-scope and tax-advice prompts to confirm guardrails hold; attempts to exceed the 5-question budget.
- **Regression testing setup?**
  *Inferred:* the golden cases double as regression tests run on each change. Formal regression harness beyond pytest **Not specified** — likely unnecessary at this scope.

### 14. Open Source Planning

- **What will you release?**
  Source code in a repository is a required deliverable, plus a short DECISIONS note and run instructions. *Inferred:* public repo for the hackathon submission.
- **Licensing considerations?**
  **Not specified — recommend confirming** (a permissive license such as MIT is a sensible default for a hackathon prototype).
- **Documentation requirements?**
  Required: live URL, one-command local run instructions (as a fallback, not a substitute), and a half-page DECISIONS note covering the open design choices and rationale.
- **Community engagement plan?**
  *Out of scope* — this is a hackathon prototype, not a maintained product.

### 15. Deployment & Operations

- **Hosting approach?**
  Railway (free tier) — a comparable easy free host to the brief's named Render default. Deploy the Python/LangGraph backend + minimal web chat frontend, publicly reachable at a live URL a judge can try.
- **CI/CD for agent updates?**
  *Inferred:* Railway's deploy-on-push from the Git repo; run tests before deploy. Heavyweight pipelines out of scope.
- **Monitoring and alerting?**
  *Inferred:* none beyond Railway's basic logs and the in-app observation trail. No alerting for a prototype.
- **Rollback strategy?**
  *Inferred:* redeploy the previous commit via Railway. Sufficient for a demo; **Not specified** as a judged concern.

### 16. Iteration Planning

- **How will you collect user feedback?**
  *Inferred:* judge feedback during the hackathon is the primary signal; no in-product feedback mechanism planned.
- **Eval-driven improvement cycle?**
  *Inferred:* extend the golden-case set as new filing statuses/edge cases are added (e.g., the dependent stretch goal), re-run tests, iterate.
- **Feature prioritization approach?**
  Core first (single W-2 → correct 1040, four pillars, deployed, working end-to-end). Stretch goals (second filing status, dependent, mid-conversation correction, UI observation trail, messy-W-2 recovery) only after the core is solid — per the brief's explicit "resist scope creep."
- **Long-term maintenance plan?**
  *Out of scope* — prototype, not a product; the only date-bound dependency is the 2025 tax-year parameter table.

---

### Summary of the four required pillars (mapped)

- **Chat loop** → LangGraph cyclic graph carrying per-session state across turns (§5, §1).
- **Tools** → typed `extract_w2`, `compute_1040`, `fill_1040_pdf`; the last produces the downloadable return (§7).
- **Guardrails** → ≤5-question budget enforced in state, deterministic math outside the model, scope/refusal rules, W-2 validation with form fallback (§3, §10, §12).
- **Observation** → in-app, judge-visible trail of decisions, tool calls, and computed line values, surfaced in the UI not just logs (§8, §3).

*This is an educational/hackathon exercise, not tax advice, and not for real filings or e-filing.*
