"""Observation pillar: a structured, append-only event trail per session.

Every meaningful thing the agent does — a decision, a tool call with its inputs
and outputs, a guardrail firing, a computed line value — is emitted here as a
typed event. The same trail is (a) streamed to the web UI's observation panel
and (b) printed as structured logs. Because events are emitted by the code that
actually runs the tools, the trail cannot drift from what the agent really did.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger("tax_agent.observability")


@dataclass
class Event:
    seq: int
    ts: float
    kind: str  # decision | tool_call | tool_result | guardrail | state | error
    label: str
    data: Dict[str, Any] = field(default_factory=dict)

    def human_ts(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.ts))


# Decision-trail phase -> (icon glyph, is-accent). Flagged entries override color.
PHASE_ICONS = {
    "Session": "◉",
    "Vision": "◇",
    "Reasoning": "·",
    "Calculation": "=",
    "Decision": "✓",
    "Guardrail": "!",
}


@dataclass
class TrailEntry:
    """A decision-trail observation shaped for the UI (phase/action/detail/conf/flag)."""
    seq: int
    phase: str
    action: str
    detail: str
    conf: float | None = None
    flag: bool = False


class ObservationLog:
    """Per-session event recorder. Cheap, in-memory, JSON-serializable.

    Two layers: low-level `emit` events (for logs) and the user-facing
    decision `trail` (phase/action/detail/conf/flag) shown in the UI drawer.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._events: List[Event] = []
        self._trail: List[TrailEntry] = []

    def observe(self, phase: str, action: str, detail: str,
                conf: float | None = None, flag: bool = False) -> TrailEntry:
        """Append a decision-trail entry and mirror it to the structured log."""
        entry = TrailEntry(seq=len(self._trail) + 1, phase=phase, action=action,
                           detail=detail, conf=conf, flag=flag)
        self._trail.append(entry)
        self.emit("guardrail" if flag else "decision", f"{phase}:{action}",
                  detail=detail, conf=conf, flag=flag)
        return entry

    def trail(self) -> List[Dict[str, Any]]:
        """Decision-trail entries shaped for the UI drawer."""
        out = []
        for e in self._trail:
            out.append({
                "seq": e.seq, "phase": e.phase, "action": e.action, "detail": e.detail,
                "conf": e.conf,
                "confText": (f"{round(e.conf * 100)}%" if e.conf is not None else ""),
                "flag": e.flag,
                "icon": PHASE_ICONS.get(e.phase, "·"),
            })
        return out

    @property
    def trail_count(self) -> int:
        return len(self._trail)

    def emit(self, kind: str, label: str, **data: Any) -> Event:
        ev = Event(seq=len(self._events) + 1, ts=time.time(), kind=kind, label=label, data=data)
        self._events.append(ev)
        logger.info(
            "obs %s #%d [%s] %s %s",
            self.session_id, ev.seq, kind, label, json.dumps(data, default=str),
        )
        return ev

    # convenience emitters used by the agent/tools
    def decision(self, label: str, **data: Any) -> Event:
        return self.emit("decision", label, **data)

    def tool_call(self, tool: str, **args: Any) -> Event:
        return self.emit("tool_call", tool, **args)

    def tool_result(self, tool: str, **result: Any) -> Event:
        return self.emit("tool_result", tool, **result)

    def guardrail(self, label: str, **data: Any) -> Event:
        return self.emit("guardrail", label, **data)

    def error(self, label: str, **data: Any) -> Event:
        return self.emit("error", label, **data)

    def as_list(self) -> List[Dict[str, Any]]:
        out = []
        for e in self._events:
            d = asdict(e)
            d["human_ts"] = e.human_ts()
            out.append(d)
        return out
