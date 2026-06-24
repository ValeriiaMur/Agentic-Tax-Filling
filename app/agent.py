"""The agentic harness — a LangGraph state machine over one user turn.

The four pillars, made concrete here:
  * Chat loop   - `TaxAgent` holds `SessionState` across turns; each user message
                  runs the compiled LangGraph once and updates that state.
  * Tools       - real actions go through `ToolRegistry` (extract_w2,
                  compute_1040, fill_1040_pdf); the graph's `finalize` node calls
                  the fill tool to produce the downloadable return.
  * Guardrails  - the scope check, the 5-question budget, status parsing, and W-2
                  validation are enforced in `conversation.advance` / guardrails,
                  not in the prompt.
  * Observation - every node decision, tool call, and result is emitted to the
                  session's ObservationLog and exposed via the API/UI.

The LLM (Claude) is optional and used only to warm up phrasing; it never decides
flow or computes a number, so the system is correct and testable without a key.
"""

from __future__ import annotations

import os
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from .conversation import Phase, SessionState, advance
from .observability import ObservationLog
from .tools import ToolRegistry


class TurnState(TypedDict, total=False):
    user_message: str
    assistant_message: str
    declined: bool
    pdf_ready: bool


class TaxAgent:
    def __init__(self, session_id: str, output_dir: str):
        self.session_id = session_id
        self.obs = ObservationLog(session_id)
        self.tools = ToolRegistry(self.obs, output_dir)
        self.state = SessionState()
        self.pdf_path: Optional[str] = None
        self._graph = self._build_graph()

    # --- graph nodes --------------------------------------------------------

    def _node_converse(self, ts: TurnState) -> TurnState:
        result = advance(self.state, ts["user_message"])
        for kind, label, data in result.events:
            self.obs.emit(kind, label, **data)
        ts["assistant_message"] = self._warm(result.message)
        ts["declined"] = result.declined
        self.obs.decision("turn_processed", phase=self.state.phase.value,
                          questions_asked=self.state.questions_asked,
                          asked_question=result.asked_question)
        return ts

    def _node_finalize(self, ts: TurnState) -> TurnState:
        # Produce the downloadable 1040 once we have a computed result.
        if self.state.result is not None:
            info = self.state.build_taxpayer()
            from .schemas import W2
            w2 = W2(
                box1_wages=float(self.state.w2.get("box1_wages") or 0),
                box2_federal_withholding=float(
                    self.state.w2.get("box2_federal_withholding") or 0),
                employee_name=self.state.w2.get("employee_name", ""),
            )
            self.pdf_path = self.tools.fill_1040_pdf(self.state.result, info, w2)
            self.state.pdf_path = self.pdf_path
            ts["pdf_ready"] = True
        return ts

    def _route_after_converse(self, ts: TurnState) -> str:
        # Go to finalize when we have a result but no PDF yet (or status changed).
        if self.state.result is not None and (
            self.pdf_path is None or self.state.phase == Phase.COMPLETE
            and not os.path.exists(self.pdf_path or "")
        ):
            return "finalize"
        return END

    def _build_graph(self):
        g = StateGraph(TurnState)
        g.add_node("converse", self._node_converse)
        g.add_node("finalize", self._node_finalize)
        g.add_edge(START, "converse")
        g.add_conditional_edges("converse", self._route_after_converse,
                                {"finalize": "finalize", END: END})
        g.add_edge("finalize", END)
        return g.compile()

    # --- public API ---------------------------------------------------------

    def handle_message(self, user_message: str) -> dict:
        self.obs.emit("state", "user_message", text=user_message[:200])
        out: TurnState = self._graph.invoke({"user_message": user_message})
        return {
            "assistant_message": out.get("assistant_message", ""),
            "phase": self.state.phase.value,
            "questions_asked": self.state.questions_asked,
            "questions_remaining": self.state.budget.remaining,
            "pdf_ready": self.pdf_path is not None and os.path.exists(self.pdf_path),
            "result": self.state.result.model_dump() if self.state.result else None,
            "events": self.obs.as_list(),
        }

    def ingest_w2(self, *, image_bytes=None, media_type="", text="") -> dict:
        """Run the extract_w2 tool, validate, and advance into confirmation."""
        from .guardrails import validate_w2_payload

        data = self.tools.extract_w2(image_bytes=image_bytes, media_type=media_type, text=text)
        ok, issues = validate_w2_payload(data)
        if not ok:
            self.obs.guardrail("w2_validation_failed", issues=issues)
            msg = "I had trouble reading that W-2: " + " ".join(issues) + \
                  " Could you re-share it, or type your Box 1 wages and Box 2 withholding?"
            return {
                "assistant_message": msg, "phase": self.state.phase.value,
                "pdf_ready": False, "events": self.obs.as_list(), "w2": data,
                "needs_retry": True,
            }
        self.state.apply_w2(data)
        self.obs.decision("w2_ingested", **{k: data.get(k) for k in
                          ("box1_wages", "box2_federal_withholding")})
        wages = float(data.get("box1_wages") or 0)
        wh = float(data.get("box2_federal_withholding") or 0)
        msg = self._warm(
            f"Thanks! I read your W-2 as ${wages:,.0f} in Box 1 wages and "
            f"${wh:,.0f} in Box 2 federal withholding. Does that look right?"
        )
        return {
            "assistant_message": msg, "phase": self.state.phase.value,
            "questions_remaining": self.state.budget.remaining,
            "pdf_ready": False, "events": self.obs.as_list(), "w2": data,
        }

    # --- optional warm phrasing via Claude ---------------------------------

    def _warm(self, message: str) -> str:
        """Lightly rephrase a policy message in a warm tone, preserving numbers.

        Off by default (deterministic). Enabled with USE_LLM_PHRASING=1 and a key.
        Any failure falls back to the original message, which is already friendly.
        """
        if os.environ.get("USE_LLM_PHRASING") != "1":
            return message
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return message
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            model = os.environ.get("CHAT_MODEL", "claude-3-5-sonnet-20241022")
            resp = client.messages.create(
                model=model, max_tokens=300,
                system=(
                    "Rewrite the assistant message to sound warm, human, and concise. "
                    "Keep it to a similar length. You MUST preserve every number, dollar "
                    "amount, and the question being asked exactly. Return only the rewrite."
                ),
                messages=[{"role": "user", "content": message}],
            )
            text = "".join(p.text for p in resp.content if getattr(p, "type", "") == "text")
            self.obs.emit("decision", "llm_phrasing_applied")
            return text.strip() or message
        except Exception as e:
            self.obs.error("llm_phrasing_failed", reason=str(e)[:120])
            return message
