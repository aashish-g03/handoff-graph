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


# ---- v2 (frozen on DEV 2026-10-16): recency-weighted memory + three explainable outcomes ----
WINDOW_DAYS = 60     # chosen on DEV: 60-day forward rate predicted bounces best (AUC 0.744 vs 0.733 at 14d)
ESCALATE_AT = 0.4    # default; the replay tunes it on TUNE (best precision-when-routed with <= 15% escalated)


def route_issue_v2(g, judge, doc: dict, t: int, first_pick: str, gate: float = ROUTING_GATE,
                   escalate_at: float = ESCALATE_AT, use_jev: bool = True) -> tuple[Route, float]:
    """Returns (route, p_off) where p_off = probability the issue leaves the bot's pick.

    Outcomes: route to a learned alternative if it wins by >= gate; else escalate if p_off >= escalate_at;
    else keep the bot's pick. With too little memory (< MEMORY_TRUST_MIN_FORWARDS in the window), keep the pick.
    """
    t0 = time.time()
    areas = areas_at(g, doc["number"], t) if doc.get("number", -1) >= 0 else []
    prior, paths = owner_prior(g, t, first_pick, areas, k=K, window_days=WINDOW_DAYS)
    top = sorted(prior, key=lambda c: -prior[c])[:K]
    prior = {c: prior[c] / sum(prior[c2] for c2 in top) for c in top}
    forwards = g.ro_query(FORWARDS_BEFORE, {"a": first_pick, "t": t}, timeout=QUERY_TIMEOUT_MS).result_set[0][0]
    if forwards < MEMORY_TRUST_MIN_FORWARDS or len(top) == 1:
        d = Decision(first_pick, prior, 1.0, 0, int((time.time() - t0) * 1000), 0,
                     f"@{first_pick} has little handoff memory; keep the pick")
        return Route(d, top, prior, paths, False), 0.0
    if use_jev:
        d = decide(g, judge, doc, t, prior, 0.0, first_pick=first_pick)
        post = d.posterior
    else:
        post = prior
        d = Decision(first_pick, prior, 0.0, 0, 0, 0, "")
    ranked = sorted(post, key=lambda c: -post[c])
    margin = post[ranked[0]] - (post[ranked[1]] if len(ranked) > 1 else 0.0)
    p_off = 1.0 - post.get(first_pick, 0.0)
    if ranked[0] != first_pick and margin >= gate:
        owner, reason = ranked[0], f"memory + text point to @{ranked[0]} (leads by {margin:.2f}): {paths.get(ranked[0], '')}"
    elif p_off >= escalate_at:
        owner, reason = None, (f"{p_off:.0%} chance @{first_pick} passes this on ({paths.get(first_pick, '')}); "
                               f"ask a human, top alternative @{next((c for c in ranked if c != first_pick), '?')}")
    else:
        owner, reason = first_pick, f"@{first_pick} likely keeps it ({1 - p_off:.0%}): {paths.get(first_pick, '')}"
    d = Decision(owner, post, margin, d.jev_calls, int((time.time() - t0) * 1000), d.input_tokens, reason,
                 d.noul, d.p_handoff)
    return Route(d, top, prior, paths, True), p_off
