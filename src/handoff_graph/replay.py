"""Time-ordered replay of real VS Code triage, scored against what actually happened.

Rules (fixed before any results were looked at):
  * Population: issues whose FIRST assignment was made by VS Code's triage bot, so the deployed
    bot's real pick is the headline baseline. Ground truth = people still assigned at the end.
  * Time: each issue is routed at its routing time T (the bot's first assignment). The learner
    advances day by day and every router query filters on `at < T`, so nothing after T is visible.
  * Periods: LEARN Jun 1-Jul 5 (memory only), TUNE Jul 6-19 (choose the escalation gate),
    DEV Jul 20-Aug 24 (all design iteration), HOLDOUT Aug 25-Sep 15 (run once with the frozen design).
    Issues routed after Sep 15 are excluded: their final owner hasn't had 30 days to settle.
  * Arms:
      bot          - the real bot's recorded first pick
      graph        - graph only: top candidate from candidate_owners (memory on), no Jev
      jev_nograph  - same decide() as below, candidates = bot pick + people most often assigned in the
                     14 days before T, uniform prior (no learned handoffs, no ownership filter)
      jev_graph    - decide() with graph candidates and graph prior
  * Gate utility (TUNE only, on issues the bot's pick handed off): +1 correct, -1 wrong, -0.5 escalation.
  * Memory trust: contrastive Jev runs only if the bot's pick has >= 10 recorded forwards before T.
  * Forwarding hops avoided (on routed issues): +1 if we skipped a bot pick that was later handed
    off and picked the final owner; -1 if we moved away from a bot pick that was actually right.

    uv run python -m handoff_graph.replay --arms bot,graph,jev_nograph,jev_graph [--limit N]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .db import PROJECT_ROOT, QUERY_TIMEOUT_MS, get_graph
from .decide import Decision, JevJudge, decide, profiles
from .events import Issue, derive_handoffs, final_owners, is_bot, parse_issue, ts
from .learner import forget_all, record_handoffs
from .agent import ROUTING_GATE, route_issue, route_issue_v2
from .router import areas_at, candidate_owners, owner_prior

RAW = PROJECT_ROOT / "data/raw/vscode_issues_2026-06-01_2026-10-15.json"
BODIES = PROJECT_ROOT / "data/raw/vscode_bodies.json"
CACHE = PROJECT_ROOT / "data/cache/jev.jsonl"
RESULTS = PROJECT_ROOT / "results"

# Protocol v2 (frozen 2026-10-16 after two designs had been inspected on the old score period):
# truth must have >= 30 days to settle before the data end (2026-10-15), so routing stops at Sep 15.
LEARN_END = ts("2026-07-06T00:00:00Z")
TUNE_END = ts("2026-07-20T00:00:00Z")
DEV_END = ts("2026-08-25T00:00:00Z")
HOLDOUT_END = ts("2026-09-15T00:00:00Z")
DAY = 86_400
K = 5
GATES = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]
MAX_ESCALATION = 0.15  # pre-registered: v2 may escalate at most 15% of issues
ESCALATION_GRID = [0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7, 0.8, 1.01]
UTILITY = {"correct": 1.0, "wrong": -1.0, "escalated": -0.5}

RECENT_ASSIGNEES = """
MATCH (:Issue)-[s:ASSIGNED]->(p:Person)
WHERE s.at < $t AND s.at >= $since AND NOT p.bot
RETURN p.login, count(*) AS n ORDER BY n DESC LIMIT $k
"""


class CachedJudge:
    """Caches Jev answers on disk keyed by the exact request, so replays are reproducible and free to re-run."""

    def __init__(self, inner: JevJudge | None):
        self.inner = inner
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        self.mem: dict[str, list] = {}
        if CACHE.exists():
            for line in CACHE.open():
                row = json.loads(line)
                self.mem[row["k"]] = row["v"]
        self.out = CACHE.open("a")
        self.lock = threading.Lock()

    def _call(self, kind: str, issue: dict, profs: dict, *extra):
        key = hashlib.sha256(json.dumps([kind, issue["title"], issue["body"][:1500], profs, list(extra)],
                                        sort_keys=True).encode()).hexdigest()
        if key in self.mem:
            v = self.mem[key]
            return (v[0], 0, *v[2:])  # cached: no new tokens spent
        if self.inner is None:
            raise RuntimeError("cache miss with no live judge")
        val = getattr(self.inner, kind)(issue, profs, *extra)
        with self.lock:
            self.mem[key] = list(val)
            self.out.write(json.dumps({"k": key, "v": list(val)}) + "\n")
            self.out.flush()
        return val

    def fit(self, issue, profs, contrast=None):
        return self._call("fit", issue, profs, contrast)

    def tiebreak(self, issue, profs):
        return self._call("tiebreak", issue, profs)


@dataclass
class Row:
    issue: int
    period: str
    t: int
    bot_pick: str
    truth: list[str]
    bot_pick_handed_off: bool
    arm: str
    pick: str | None
    margin: float
    candidates: list[str]
    truth_in_candidates: bool
    jev_calls: int
    latency_ms: int
    input_tokens: int
    reason: str
    p_handoff: float | None = None
    p_off: float | None = None


# Protocol for the fresh spring holdout (set 2026-10-16 before any spring result existed). v2 design frozen on DEV.
SPRING = {
    "raw": PROJECT_ROOT / "data/raw/vscode_issues_2026-01-01_2026-05-31.json",
    "bodies": PROJECT_ROOT / "data/raw/vscode_bodies_2026H1.json",
    "repo": "microsoft/vscode@2026H1",
    "learn_end": ts("2026-03-18T00:00:00Z"),
    "tune_end": ts("2026-04-01T00:00:00Z"),
    "holdout_end": ts("2026-05-16T00:00:00Z"),
}
DATASET = "summer"


def period_of(t: int) -> str:
    if DATASET == "spring":
        if t < SPRING["learn_end"]:
            return "learn"
        if t < SPRING["tune_end"]:
            return "tune"
        return "holdout" if t < SPRING["holdout_end"] else "unsettled"
    if t < LEARN_END:
        return "learn"
    if t < TUNE_END:
        return "tune"
    if t < DEV_END:
        return "dev"
    if t < HOLDOUT_END:
        return "holdout"
    return "unsettled"  # truth not settled yet; never scored


def load() -> tuple[list[Issue], dict[str, str]]:
    raw_path, bodies_path = (SPRING["raw"], SPRING["bodies"]) if DATASET == "spring" else (RAW, BODIES)
    issues = [parse_issue(r) for r in json.load(raw_path.open())]
    bodies = json.load(bodies_path.open()) if bodies_path.exists() else {}
    return sorted(issues, key=lambda i: i.routing_time), bodies


def population(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.first_pick and is_bot(i.first_pick.by) and final_owners(i)]


def route(g, judge, arm: str, issue: Issue, body: str, gate: float) -> Row:
    t, bot_pick = issue.routing_time, issue.first_pick.login
    truth = list(final_owners(issue))
    handed = any(h.from_login == bot_pick for h in derive_handoffs(issue))
    doc = {"number": issue.number, "title": issue.title, "body": body or ""}
    t0 = time.time()
    if arm == "bot":
        cands, d = [bot_pick], Decision(bot_pick, {bot_pick: 1.0}, 1.0, 0, 0, 0, "deployed bot's pick")
    elif arm == "graph_v0":  # first scoring design (heuristic scores, ignored base rates); kept for the record
        cs = candidate_owners(g, issue.number, t, bot_pick, k=K)
        cands = [c.login for c in cs]
        d = Decision(cands[0], {}, 1.0, 0, int((time.time() - t0) * 1000), 0, " | ".join(cs[0].reasons))
    elif arm == "graph":
        prior, path = owner_prior(g, t, bot_pick, areas_at(g, issue.number, t), k=K)
        cands = sorted(prior, key=lambda c: -prior[c])[:K]
        d = Decision(cands[0], prior, 1.0, 0, int((time.time() - t0) * 1000), 0, path[cands[0]])
    elif arm == "jev_graph":
        r = route_issue(g, judge, doc, t, bot_pick, gate)
        cands, d = r.candidates, r.decision
    elif arm in ("graph_v2", "jev_graph_v2"):
        # v2 rows store the keep/alternative decision with escalation OFF; escalation is applied after tuning.
        r, p_off = route_issue_v2(g, judge, doc, t, bot_pick, ROUTING_GATE, escalate_at=2.0, use_jev=(arm == "jev_graph_v2"))
        cands, d = r.candidates, r.decision
        row = Row(issue.number, period_of(t), t, bot_pick, truth, handed, arm, d.owner, d.margin, cands,
                  any(c in truth for c in cands), d.jev_calls, d.latency_ms, d.input_tokens, d.reason,
                  d.p_handoff, p_off)
        return row
    elif arm == "jev_nograph":
        rows = g.ro_query(RECENT_ASSIGNEES, {"t": t, "since": t - 14 * DAY, "k": K},
                          timeout=QUERY_TIMEOUT_MS).result_set
        cands = list(dict.fromkeys([bot_pick] + [r[0] for r in rows]))[:K]
        d = decide(g, judge, doc, t, {c: 1 / len(cands) for c in cands}, gate)
    elif arm == "jev_keep":  # control: Jev alone asks "should the bot's pick keep this?" - no alternatives
        cands = [bot_pick]
        profs = profiles(g, [bot_pick], issue.number, t)
        lk, tokens, _ = judge.fit(doc, profs)
        p_keep = lk[bot_pick]
        d = Decision(bot_pick, {bot_pick: p_keep}, p_keep, 1, int((time.time() - t0) * 1000), tokens,
                     f"keep probability {p_keep:.2f}")
    else:
        raise ValueError(arm)
    return Row(issue.number, period_of(t), t, bot_pick, truth, handed, arm, d.owner, d.margin, cands,
               any(c in truth for c in cands), d.jev_calls, d.latency_ms, d.input_tokens, d.reason,
               d.p_handoff)


def outcome(r: Row) -> str:
    if r.pick is None:
        return "escalated"
    return "correct" if r.pick in r.truth else "wrong"


def summarise(rows: list[Row]) -> dict:
    out = {}
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r.arm].append(r)
    for arm, rs in by_arm.items():
        n = len(rs)
        oc = [outcome(r) for r in rs]
        routed = [r for r, o in zip(rs, oc) if o != "escalated"]
        hops = sum(1 for r in routed if r.pick != r.bot_pick and r.bot_pick_handed_off and r.pick in r.truth) \
            - sum(1 for r in routed if r.pick != r.bot_pick and r.bot_pick in r.truth)
        reassigned = [r for r in rs if r.bot_pick_handed_off]
        out[arm] = {
            "issues": n,
            "top1_accuracy": round(oc.count("correct") / n, 4) if n else None,
            "escalated": round(oc.count("escalated") / n, 4) if n else None,
            "precision_when_routed": round(oc.count("correct") / len(routed), 4) if routed else None,
            "truth_in_candidates": round(sum(r.truth_in_candidates for r in rs) / n, 4) if n else None,
            "reassigned_subset": len(reassigned),
            "reassigned_subset_correct": sum(1 for r in reassigned if r.pick in r.truth),
            "net_forwarding_hops_avoided": hops,
            "jev_calls_per_issue": round(sum(r.jev_calls for r in rs) / n, 3) if n else None,
            "new_input_tokens": sum(r.input_tokens for r in rs),
            "median_latency_ms": sorted(r.latency_ms for r in rs)[n // 2] if n else None,
        }
    return out


def run(arms: list[str], gate: float | None, limit: int | None, workers: int, live: bool,
        holdout: bool = False) -> Path:
    g = get_graph(SPRING["repo"] if DATASET == "spring" else "microsoft/vscode")
    issues, bodies = load()
    pop = population(issues)
    handoffs = sorted((h for i in issues for h in derive_handoffs(i)), key=lambda h: h.at)
    judge = CachedJudge(JevJudge() if live else None) if any(a.startswith("jev") for a in arms) else None
    forget_all(g)

    eval_period = "holdout" if holdout else "dev"
    targets = [i for i in pop if period_of(i.routing_time) in ("tune", eval_period)]
    if limit:
        tune = [i for i in targets if period_of(i.routing_time) == "tune"]
        ev = [i for i in targets if period_of(i.routing_time) == eval_period]
        targets = tune[::max(1, len(tune) // max(1, limit // 2))][: max(1, limit // 2)] + \
            ev[::max(1, len(ev) // limit)][:limit]
    gates = GATES if gate is None else [gate]

    rows: list[Row] = []
    hp = 0
    days = sorted({i.routing_time // DAY for i in targets})
    for day in days:
        day_start = day * DAY
        batch = []
        while hp < len(handoffs) and handoffs[hp].at < day_start:
            batch.append(handoffs[hp])
            hp += 1
        record_handoffs(g, batch)  # the learner only knows what happened before this day
        todays = [i for i in targets if i.routing_time // DAY == day]
        with cf.ThreadPoolExecutor(workers) as ex:
            futs = [ex.submit(route, g, judge, arm, i, bodies.get(str(i.number), ""), 0.0)
                    for i in todays for arm in arms]
            rows.extend(f.result() for f in futs)

    # Gate is applied after the fact on stored margins (0.0 gate = always route), tuned on TUNE only.
    def gated(rs: list[Row], gv: float) -> list[Row]:
        return [Row(**{**asdict(r), "pick": (r.pick if (not r.arm.startswith("jev") or r.margin >= gv) else None)})
                for r in rs]

    def escalated_v2(rs: list[Row], th: float) -> list[Row]:
        return [Row(**{**asdict(r), "pick": (None if (r.p_off or 0) >= th and r.pick == r.bot_pick else r.pick)})
                for r in rs]

    tuned = {}
    for arm in [a for a in arms if a.endswith("_v2")]:
        tune_rows = [r for r in rows if r.arm == arm and r.period == "tune"]
        def prec(th):
            rs = escalated_v2(tune_rows, th)
            routed = [r for r in rs if r.pick is not None]
            esc = 1 - len(routed) / max(1, len(rs))
            return (sum(r.pick in r.truth for r in routed) / max(1, len(routed))) if esc <= MAX_ESCALATION else -1
        tuned[arm] = max(ESCALATION_GRID, key=prec)
    for arm in arms:
        if not arm.startswith("jev") or arm.endswith("_v2"):
            continue
        # Pre-registered: tune on TUNE issues the bot's pick handed off (pooled utility always says "never escalate").
        tune_rows = [r for r in rows if r.arm == arm and r.period == "tune" and r.bot_pick_handed_off]
        best = max(gates, key=lambda gv: sum(UTILITY[outcome(r)] for r in gated(tune_rows, gv)))
        tuned[arm] = best
    final = [r for r in rows if not r.arm.startswith("jev") and not r.arm.endswith("_v2")] + \
            [r for arm, gv in tuned.items() if not arm.endswith("_v2") for r in gated([x for x in rows if x.arm == arm], gv)] + \
            [r for arm, th in tuned.items() if arm.endswith("_v2") for r in escalated_v2([x for x in rows if x.arm == arm], th)]

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS / f"replay_{stamp}.json"
    summary = {
        "rules": __doc__,
        "tuned_gates": tuned,
        "eval_period": eval_period,
        "score": summarise([r for r in final if r.period == eval_period]),
        "tune": summarise([r for r in final if r.period == "tune"]),
        "counts": {"population": len(pop), "routed_targets": len(targets), "handoffs_learned": hp},
    }
    json.dump({"summary": summary, "rows": [asdict(r) for r in final]}, path.open("w"), indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != "rules"}, indent=1))
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arms", default="bot,graph")
    ap.add_argument("--gate", type=float, default=None, help="fixed gate instead of tuning on TUNE")
    ap.add_argument("--limit", type=int, default=None, help="score a time-spread sample of N issues")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--offline", action="store_true", help="use cached Jev answers only")
    ap.add_argument("--holdout", action="store_true", help="evaluate on HOLDOUT (run once, frozen design only)")
    ap.add_argument("--dataset", choices=["summer", "spring"], default="summer",
                    help="spring = fresh Jan-May 2026 holdout (always evaluates its HOLDOUT)")
    a = ap.parse_args()
    global DATASET
    DATASET = a.dataset
    if DATASET == "spring":
        a.holdout = True
    print("results:", run(a.arms.split(","), a.gate, a.limit, a.workers, not a.offline, a.holdout))


if __name__ == "__main__":
    main()
