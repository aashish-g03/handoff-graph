"""The routing agent: graph memory + Jev, as one function used by both the replay and the MCP server."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .db import QUERY_TIMEOUT_MS
from .decide import Decision, decide
from .router import areas_at, owner_prior

K = 5
MEMORY_TRUST_MIN_FORWARDS = 10  # pre-registered: only trust handoff memory for people with >= 10 forwards before T
ROUTING_GATE = 0.5              # escalation gate tuned on the replay's TUNE period (see docs/RESULTS.md)

FORWARDS_BEFORE = """
MATCH (:Person {login: $a})-[h:HANDED_OFF]->()
WHERE h.at < $t AND h.kind IN ['forward', 'reassign']
RETURN count(h)
"""


@dataclass
class Route:
    decision: Decision
    candidates: list[str]
    prior: dict[str, float]
    paths: dict[str, str]
    memory_trusted: bool


def route_issue(g, judge, doc: dict, t: int, first_pick: str, gate: float = ROUTING_GATE,
                areas: list[str] | None = None) -> Route:
    """Route `doc` (number, title, body) proposed for `first_pick`, using only what the graph knew before t."""
    t0 = time.time()
    if areas is None:
        areas = areas_at(g, doc["number"], t) if doc.get("number", -1) >= 0 else []
    prior, paths = owner_prior(g, t, first_pick, areas, k=K)
    top = sorted(prior, key=lambda c: -prior[c])[:K]
    prior = {c: prior[c] / sum(prior[c2] for c2 in top) for c in top}
    forwards = g.ro_query(FORWARDS_BEFORE, {"a": first_pick, "t": t}, timeout=QUERY_TIMEOUT_MS).result_set[0][0]
    if forwards < MEMORY_TRUST_MIN_FORWARDS:
        d = Decision(first_pick, prior, 1.0, 0, int((time.time() - t0) * 1000), 0,
                     f"@{first_pick} has only {forwards} recorded forwards; memory not trusted, keep the pick")
        return Route(d, top, prior, paths, False)
    d = decide(g, judge, doc, t, prior, gate, first_pick=first_pick)
    return Route(d, top, prior, paths, True)
