"""LangGraph compute pipeline — the tool-running core of the harness.

`TaxSession` (in conversation.py) drives the UI stage machine; when the last
question is answered it calls `run_compute_graph`, a small but real LangGraph
that runs two tool nodes in sequence:

    compute (compute_1040 tool) ──▶ finalize (fill_1040_pdf tool)

Both tools are invoked through the session's `ToolRegistry`, so every call and
result lands on the decision trail. Keeping this as an explicit graph makes the
"tools" pillar legible: you can point at the nodes and see the real actions.
"""

from __future__ import annotations

from typing import Optional, Tuple, TypedDict

from langgraph.graph import END, START, StateGraph

from .schemas import Form1040Result, TaxpayerInfo, W2


class ComputeState(TypedDict, total=False):
    result: Form1040Result
    pdf_path: str


def run_compute_graph(session, w2: W2, info: TaxpayerInfo) -> Tuple[Form1040Result, str]:
    """Run compute → finalize through the session's tools and return (result, pdf_path)."""

    def node_compute(state: ComputeState) -> ComputeState:
        return {"result": session.tools.compute_1040(w2, info)}

    def node_finalize(state: ComputeState) -> ComputeState:
        return {"pdf_path": session.tools.fill_1040_pdf(state["result"], info, w2)}

    g = StateGraph(ComputeState)
    g.add_node("compute", node_compute)
    g.add_node("finalize", node_finalize)
    g.add_edge(START, "compute")
    g.add_edge("compute", "finalize")
    g.add_edge("finalize", END)
    # Initialize channels explicitly: this LangGraph build rejects an empty
    # initial state with multiple optional channels.
    out = g.compile().invoke({"result": None, "pdf_path": ""})
    return out["result"], out["pdf_path"]
