"""The router agent: read-only. Proposes owners for an issue *as of* a time T, with the graph path.

Every query takes $t and only looks at facts that existed before it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .db import QUERY_TIMEOUT_MS

# Who has A learned to hand this kind of work to? Only handoffs recorded before $t count.
LEARNED_FORWARDS = """
MATCH (a:Person {login: $first_pick})-[h:HANDED_OFF]->(b:Person)
WHERE h.at < $t AND h.kind IN ['forward', 'reassign']
WITH b, count(h) AS times, max(h.at) AS last_at, collect(h.issue)[0..5] AS examples
RETURN b.login AS login, times, last_at, examples
ORDER BY times DESC, last_at DESC
LIMIT $k
"""

# Who owned (was still assigned to) issues carrying these areas, as of $t?
AREA_OWNERS = """
MATCH (a:Area)<-[l:HAS_LABEL]-(i:Issue)-[s:ASSIGNED]->(p:Person)
WHERE a.name IN $areas AND l.added_at <= $t AND s.at < $t AND s.removed_at > $t AND NOT p.bot
WITH p, count(DISTINCT i) AS issues, collect(DISTINCT a.name) AS via_areas, max(s.at) AS last_at
RETURN p.login AS login, issues, via_areas, last_at
ORDER BY issues DESC, last_at DESC
LIMIT $k
"""

# Areas on the issue as of $t. Labels applied in the same second as routing (the bot labels and assigns
# in one action) count as known; anything a human adds later does not.
AREAS_AT = """
MATCH (i:Issue {number: $number})-[l:HAS_LABEL]->(a:Area)
WHERE l.added_at <= $t AND l.removed_at > $t
RETURN collect(a.name) AS areas
"""


# How many issues did the bot route to this person before $t? (the denominator for their forward rate)
BOT_ROUTED_TO = """
MATCH (:Issue)-[s:ASSIGNED]->(p:Person {login: $login})
WHERE s.by_bot AND s.at < $t
RETURN count(s)
"""

AREA_OWNER_PRIOR = 0.02  # small prior so Jev can still surface an area owner the memory never saw


def owner_prior(g, t: int, first_pick: str, areas: list[str], k: int = 5) -> tuple[dict[str, float], dict[str, str]]:
    """A probability model of where the bot's pick ends up, from memory as of t.

        P(stays with A)   = (routed_to_A - forwarded_by_A + 1) / (routed_to_A + 2)
        P(goes to B)      = forwards_A_to_B / (routed_to_A + 2)
        area owners       = AREA_OWNER_PRIOR each (only if not already a candidate)
    then normalised. Returns (prior, human-readable path per candidate).
    """
    routed = g.ro_query(BOT_ROUTED_TO, {"login": first_pick, "t": t}, timeout=QUERY_TIMEOUT_MS).result_set[0][0]
    fwd = g.ro_query(LEARNED_FORWARDS, {"first_pick": first_pick, "t": t, "k": k},
                     timeout=QUERY_TIMEOUT_MS).result_set
    forwarded = sum(r[1] for r in fwd)
    denom = routed + 2
    prior = {first_pick: max(routed - forwarded + 1, 1) / denom}
    path = {first_pick: f"bot routes to @{first_pick}; kept {max(routed - forwarded, 0)}/{routed} so far"}
    for login, times, _last, examples in fwd:
        prior[login] = prior.get(login, 0.0) + times / denom
        path[login] = (f"bot routes to @{first_pick} -> @{first_pick} handed {times}/{routed} to @{login} "
                       f"(e.g. #{', #'.join(map(str, examples[:3]))})")
    if areas:
        for login, issues, via, _l in g.ro_query(AREA_OWNERS, {"areas": areas, "t": t, "k": k},
                                                  timeout=QUERY_TIMEOUT_MS).result_set:
            if login not in prior:
                prior[login] = AREA_OWNER_PRIOR
                path[login] = f"owns {issues} open issue(s) in {', '.join(via)}"
    total = sum(prior.values())
    return {c: v / total for c, v in prior.items()}, path


@dataclass
class Candidate:
    login: str
    score: float
    reasons: list[str] = field(default_factory=list)


def areas_at(g, number: int, t: int) -> list[str]:
    rows = g.ro_query(AREAS_AT, {"number": number, "t": t}, timeout=QUERY_TIMEOUT_MS).result_set
    return rows[0][0] if rows else []


def candidate_owners(g, number: int, t: int, first_pick: str | None, areas: list[str] | None = None,
                     k: int = 5, use_memory: bool = True) -> list[Candidate]:
    """Rank people who could own issue `number` at time `t`.

    first_pick: who the existing process (e.g. the triage bot) would assign. If memory shows that
    person reliably forwards this work to someone else, that someone is ranked up, with the path.
    """
    areas = areas if areas is not None else areas_at(g, number, t)
    cands: dict[str, Candidate] = {}

    def add(login: str, score: float, reason: str) -> None:
        c = cands.setdefault(login, Candidate(login, 0.0))
        c.score += score
        c.reasons.append(reason)

    if first_pick:
        add(first_pick, 1.0, f"current process picks @{first_pick}")
    if use_memory and first_pick:
        rows = g.ro_query(LEARNED_FORWARDS, {"first_pick": first_pick, "t": t, "k": k},
                          timeout=QUERY_TIMEOUT_MS).result_set
        forwarded = sum(r[1] for r in rows)
        for login, times, _last, examples in rows:
            add(login, 3.0 * times / max(forwarded, 1),
                f"@{first_pick} handed {times} earlier issue(s) to @{login} "
                f"(e.g. #{', #'.join(map(str, examples[:3]))})")
    if areas:
        rows = g.ro_query(AREA_OWNERS, {"areas": areas, "t": t, "k": k}, timeout=QUERY_TIMEOUT_MS).result_set
        total = sum(r[1] for r in rows)
        for login, issues, via, _last in rows:
            add(login, 1.5 * issues / max(total, 1), f"owned {issues} open issue(s) in {', '.join(via)}")
    return sorted(cands.values(), key=lambda c: -c.score)[:k]
