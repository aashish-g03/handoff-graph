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
PROFILE_TITLES = 8

# Issues a person owned as of $t: assigned before t and not handed away by t.
PROFILE = """
MATCH (i:Issue)-[s:ASSIGNED]->(p:Person {login: $login})
WHERE s.at < $t AND s.removed_at > $t AND i.number <> $number
RETURN i.title ORDER BY s.at DESC LIMIT $k
"""

# Contrastive memory (graph-on only): what the bot's pick A KEPT vs what A HANDED to each B, before $t.
KEPT_BY = """
MATCH (i:Issue)-[s:ASSIGNED]->(:Person {login: $a})
WHERE s.by_bot AND s.at < $t AND s.removed_at > $t AND i.number <> $number
RETURN i.title ORDER BY s.at DESC LIMIT $k
"""
HANDED_BY = """
MATCH (:Person {login: $a})-[h:HANDED_OFF]->(b:Person)
WHERE h.at < $t AND h.issue <> $number AND ($b = '' OR b.login = $b)
MATCH (i:Issue {number: h.issue})
RETURN i.title ORDER BY h.at DESC LIMIT $k
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
    p_handoff: float | None = None


def _titles(g, q: str, params: dict) -> list[str]:
    return [r[0] for r in g.ro_query(q, {**params, "k": PROFILE_TITLES}, timeout=QUERY_TIMEOUT_MS).result_set]


def profiles(g, logins: list[str], number: int, t: int, first_pick: str | None = None) -> dict[str, list[str]]:
    """Evidence shown to Jev per candidate. With `first_pick` (graph memory on), A's profile is what A
    kept and B's is what A handed to B; otherwise (or with no such memory) general ownership."""
    out = {}
    for login in logins:
        titles: list[str] = []
        if first_pick and login == first_pick:
            titles = _titles(g, KEPT_BY, {"a": first_pick, "t": t, "number": number})
        elif first_pick:
            titles = _titles(g, HANDED_BY, {"a": first_pick, "b": login, "t": t, "number": number})
        out[login] = titles or _titles(g, PROFILE, {"login": login, "t": t, "number": number})
    return out


def handoff_contrast(g, first_pick: str, number: int, t: int) -> tuple[list[str], list[str]]:
    return (_titles(g, KEPT_BY, {"a": first_pick, "t": t, "number": number}),
            _titles(g, HANDED_BY, {"a": first_pick, "b": "", "t": t, "number": number}))


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

    def fit(self, issue: dict, profs: dict[str, list[str]],
            contrast: tuple[list[str], list[str]] | None = None) -> tuple[dict[str, float], int, float | None]:
        from typesafe_sdk import Noul, Score
        keys = {f"fit_{k}": login for k, login in enumerate(profs)}
        extra = {}
        if contrast and contrast[0] and contrast[1]:
            extra["handoff"] = Score(
                instructions={
                    "kept_examples": contrast[0],
                    "handed_off_examples": contrast[1],
                    "question": "Is the issue in `issue_title` and `issue_body` more like `kept_examples` "
                                "(the engineer keeps it) or `handed_off_examples` (the engineer hands it to someone else)?",
                },
                criteria=["Like `kept_examples`: the engineer keeps it",
                          "Like `handed_off_examples`: the engineer hands it off"],
            )
        r = self.client.system_one(
            state={"issue_title": issue["title"], "issue_body": issue["body"][:BODY_CHARS]},
            questions={**extra, **{
                key: Noul(
                    instructions={
                        "engineer_recent_issues": profs[login] or ["(no recent issues)"],
                        "question": "Is the issue in `issue_title` and `issue_body` the same kind of work "
                                    "as `engineer_recent_issues`, so this engineer should own it?",
                    },
                )
                for key, login in keys.items()
            }},
        )
        # 2-level Score: .score is the expected level in [0, 1] = P(hands off). (SDK keys probabilities by int.)
        p_handoff = float(r.scores["handoff"].score) if extra else None
        return {login: r.nouls[key].noul for key, login in keys.items()}, r.usage.input_tokens, p_handoff

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


def decide(g, judge, issue: dict, t: int, prior: dict[str, float], gate: float,
           first_pick: str | None = None) -> Decision:
    """Pick an owner for `issue` among `prior`'s candidates, as of time t.

    With `first_pick` (graph memory on) Jev sees contrastive evidence: what that person kept vs handed
    to each candidate, plus a keep-or-hand-off Score. Likelihoods then become
    noul(A) * (1 - p_handoff) for A and noul(B) * p_handoff for everyone else (fixed rule).
    """
    t0 = time.time()
    cands = list(prior)
    if not cands:
        return Decision(None, {}, 0.0, 0, 0, 0, "no candidates in the graph")
    if len(cands) == 1:
        only = cands[0]
        return Decision(only, {only: 1.0}, 1.0, 0, int((time.time() - t0) * 1000), 0, "single candidate")
    profs = profiles(g, cands, issue["number"], t, first_pick)
    contrast = handoff_contrast(g, first_pick, issue["number"], t) if first_pick else None
    likelihood, tokens, p_handoff = judge.fit(issue, profs, contrast)
    if first_pick and p_handoff is not None:
        likelihood = {c: v * ((1 - p_handoff) if c == first_pick else p_handoff) for c, v in likelihood.items()}
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
    return Decision(owner, posterior, margin, calls, int((time.time() - t0) * 1000), tokens, reason, likelihood,
                    p_handoff)
