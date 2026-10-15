"""The decision function: graph evidence x Jev judgement -> owner, or "ask a human".

Both replay arms (graph-on and Jev-without-graph) call `decide()` with the same issue text and the
same question types; only the candidate set and the prior differ. That way the replay measures the
graph, not prompt wording.

Rule (fixed before looking at results):
    prior(c)      = graph evidence share for candidate c (uniform if there is none)
    likelihood(c) = Jev Noul "is this the kind of issue c handles?" (one independent question each)
    posterior     = prior * likelihood, normalised
    if top-1 margin < TIE_MARGIN: one Jev Choice among the close candidates breaks the tie
    if the final margin < gate threshold: escalate to a human instead of routing
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field

from .db import QUERY_TIMEOUT_MS

TIE_MARGIN = 0.15
BODY_CHARS = 1500
PROFILE_TITLES = 6

# Issues a person owned as of $t: assigned before t and not handed away by t.
PROFILE = """
MATCH (i:Issue)-[s:ASSIGNED]->(p:Person {login: $login})
WHERE s.at < $t AND s.removed_at > $t AND i.number <> $number
RETURN i.title ORDER BY s.at DESC LIMIT $k
"""


@dataclass
class Decision:
    owner: str | None              # None means "escalate to a human"
    posterior: dict[str, float]
    margin: float
    jev_calls: int
    latency_ms: int
    input_tokens: int
    reason: str
    noul: dict[str, float] = field(default_factory=dict)


def profiles(g, logins: list[str], number: int, t: int) -> dict[str, list[str]]:
    return {
        login: [r[0] for r in g.ro_query(PROFILE, {"login": login, "t": t, "number": number, "k": PROFILE_TITLES},
                                         timeout=QUERY_TIMEOUT_MS).result_set]
        for login in logins
    }


def combine(prior: dict[str, float], likelihood: dict[str, float]) -> dict[str, float]:
    raw = {c: prior.get(c, 0.0) * likelihood.get(c, 0.0) for c in prior}
    total = sum(raw.values())
    if total <= 0:
        return {c: 1 / len(prior) for c in prior}
    return {c: v / total for c, v in raw.items()}


def top_margin(posterior: dict[str, float]) -> tuple[list[str], float]:
    ranked = sorted(posterior, key=lambda c: -posterior[c])
    margin = posterior[ranked[0]] - (posterior[ranked[1]] if len(ranked) > 1 else 0.0)
    return ranked, margin


class JevJudge:
    """Thin wrapper over TypeSafe Jev so the replay can swap in a fake."""

    def __init__(self, model: str | None = None):
        from typesafe_sdk import TypeSafeClient
        self.client = TypeSafeClient(model=model or os.environ.get("JEV_MODEL", "jev-1.14.0"))

    def fit(self, issue: dict, profs: dict[str, list[str]]) -> tuple[dict[str, float], int]:
        from typesafe_sdk import Noul
        keys = {f"fit_{k}": login for k, login in enumerate(profs)}
        r = self.client.system_one(
            state={"issue_title": issue["title"], "issue_body": issue["body"][:BODY_CHARS]},
            questions={
                key: Noul(
                    instructions={
                        "engineer_recent_issues": profs[login] or ["(no recent issues)"],
                        "question": "Is the issue in `issue_title` and `issue_body` the same kind of work "
                                    "as `engineer_recent_issues`, so this engineer should own it?",
                    },
                )
                for key, login in keys.items()
            },
        )
        return {login: r.nouls[key].noul for key, login in keys.items()}, r.usage.input_tokens

    def tiebreak(self, issue: dict, profs: dict[str, list[str]]) -> tuple[dict[str, float], int]:
        from typesafe_sdk import Choice
        order = list(profs)
        random.Random(issue["number"]).shuffle(order)  # Jev leans to the first option; don't let our order decide
        r = self.client.system_one(
            state={"issue_title": issue["title"], "issue_body": issue["body"][:BODY_CHARS]},
            questions={"owner": Choice(
                instructions="Which engineer should own the issue in `issue_title` and `issue_body`, "
                             "judging by the kind of issues each one recently owned?",
                criteria={login: {"recently_owned": profs[login] or ["(none)"]} for login in order},
            )},
        )
        return dict(r.choices["owner"].probabilities), r.usage.input_tokens


def decide(g, judge, issue: dict, t: int, prior: dict[str, float], gate: float) -> Decision:
    """Pick an owner for `issue` among `prior`'s candidates, as of time t."""
    t0 = time.time()
    cands = list(prior)
    if not cands:
        return Decision(None, {}, 0.0, 0, 0, 0, "no candidates in the graph")
    if len(cands) == 1:
        only = cands[0]
        return Decision(only, {only: 1.0}, 1.0, 0, int((time.time() - t0) * 1000), 0, "single candidate")
    profs = profiles(g, cands, issue["number"], t)
    likelihood, tokens = judge.fit(issue, profs)
    posterior = combine(prior, likelihood)
    ranked, margin = top_margin(posterior)
    calls = 1
    if margin < TIE_MARGIN:
        close = [c for c in ranked if posterior[ranked[0]] - posterior[c] < TIE_MARGIN][:5]
        if len(close) > 1:
            probs, extra = judge.tiebreak(issue, {c: profs[c] for c in close})
            calls, tokens = 2, tokens + extra
            mass = sum(posterior[c] for c in close)
            for c in close:
                posterior[c] = mass * probs.get(c, 0.0)
            ranked, margin = top_margin(posterior)
    owner = ranked[0] if margin >= gate else None
    reason = (f"@{ranked[0]} leads by {margin:.2f}" if owner
              else f"too close to call (margin {margin:.2f} < {gate:.2f}); ask a human")
    return Decision(owner, posterior, margin, calls, int((time.time() - t0) * 1000), tokens, reason, likelihood)
