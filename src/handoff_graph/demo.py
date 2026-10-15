"""Demo player: replays the RECORDED held-out decisions issue by issue, with running counters.

Nothing is recomputed; it reads the rows the one-time HOLDOUT run wrote, so what you see on screen is
exactly what was scored.

    uv run python -m handoff_graph.demo results/replay_20261015T203103Z.json --n 40 --delay 0.35
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict

ARMS = [("bot", "VS Code bot"), ("jev_nograph", "Jev, no graph"), ("jev_graph", "Jev + graph")]
GREEN, RED, YELLOW, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"


def verdict(row: dict) -> tuple[str, str]:
    if row["pick"] is None:
        return "asks a human", YELLOW
    return (f"@{row['pick']}", GREEN) if row["pick"] in row["truth"] else (f"@{row['pick']}", RED)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--delay", type=float, default=0.35)
    ap.add_argument("--graph-arm", default=None, help="override, e.g. jev_graph_v2 for the spring file")
    a = ap.parse_args()
    data = json.load(open(a.results))
    period = data["summary"]["eval_period"]
    arms = [(a.graph_arm, "Jev + graph") if k == "jev_graph" and a.graph_arm else (k, label) for k, label in ARMS]
    by_issue: dict[int, dict] = defaultdict(dict)
    for r in data["rows"]:
        if r["period"] == period:
            by_issue[r["issue"]][r["arm"]] = r
    issues = sorted((i for i, v in by_issue.items() if all(k in v for k, _ in arms)), key=lambda i: by_issue[i]["bot"]["t"])
    step = max(1, len(issues) // a.n)
    shown = issues[::step][: a.n]
    count = {k: defaultdict(int) for k, _ in arms}
    print(f"{BOLD}Replaying {len(shown)} recorded {period.upper()} decisions on microsoft/vscode{RESET}\n")
    for n, num in enumerate(shown, 1):
        rows = by_issue[num]
        print(f"{BOLD}#{num}{RESET}  {DIM}bot proposed @{rows['bot']['bot_pick']}; final owner: "
              f"{', '.join('@' + t for t in rows['bot']['truth'])}{RESET}")
        for k, label in arms:
            text, colour = verdict(rows[k])
            count[k]["escalated" if rows[k]["pick"] is None else ("right" if colour == GREEN else "wrong")] += 1
            print(f"   {label:14s} {colour}{text}{RESET}")
        line = "   " + "   ".join(
            f"{label}: {GREEN}{count[k]['right']}✓{RESET} {RED}{count[k]['wrong']}✗{RESET} {YELLOW}{count[k]['escalated']}?{RESET}"
            for k, label in arms)
        print(f"{DIM}{line}{RESET}\n")
        time.sleep(a.delay)
    print(f"{BOLD}Full {period} results (all issues): {RESET}")
    s = data["summary"]["score"]
    for k, label in arms:
        v = s[k]
        print(f"   {label:14s} right first time {v['top1_accuracy']:.1%}   asks a human {v['escalated']:.1%}   "
              f"precision when routed {v['precision_when_routed']:.1%}")


if __name__ == "__main__":
    main()
