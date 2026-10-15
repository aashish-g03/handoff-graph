"""The learner agent: watches assignment events and records handoffs as graph memory.

It is the only component that writes learned knowledge. In a replay it advances in time
order, so the router at time T can only see handoffs that had already happened.
"""
from __future__ import annotations

from .db import QUERY_TIMEOUT_MS
from .events import Handoff

RECORD_HANDOFF = """
UNWIND $rows AS r
MATCH (a:Person {login: r.from_login}), (b:Person {login: r.to_login})
MERGE (a)-[h:HANDED_OFF {issue: r.issue, at: r.at}]->(b)
SET h.by = r.by, h.kind = r.kind, h.first_pick_by_bot = r.first_pick_by_bot, h.areas = r.areas
"""


def record_handoffs(g, handoffs: list[Handoff]) -> int:
    rows = [{
        "issue": h.issue, "from_login": h.from_login, "to_login": h.to_login, "at": h.at,
        "by": h.by or "", "kind": h.kind, "first_pick_by_bot": h.first_pick_by_bot,
        "areas": list(h.areas),
    } for h in handoffs]
    if rows:
        g.query(RECORD_HANDOFF, {"rows": rows}, timeout=QUERY_TIMEOUT_MS)
    return len(rows)


def forget_all(g) -> None:
    """Reset learned memory (used at the start of a replay)."""
    g.query("MATCH ()-[h:HANDED_OFF]->() DELETE h", timeout=QUERY_TIMEOUT_MS)
