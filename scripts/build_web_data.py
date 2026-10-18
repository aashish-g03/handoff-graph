"""Build src/handoff_graph/web/data.json for the public page from the committed holdout results.

Everything is taken from recorded results (nothing recomputed) plus public issue titles/bodies.
    uv run python scripts/build_web_data.py
"""
import collections
import json
from pathlib import Path

from handoff_graph.events import derive_handoffs, parse_issue

ROOT = Path(__file__).resolve().parents[1]
SUMMER = ROOT / "results/replay_20261015T203103Z.json"
SPRING = ROOT / "results/replay_20261015T210435Z.json"
RAW = ROOT / "data/raw/vscode_issues_2026-06-01_2026-10-15.json"
BODIES = ROOT / "data/raw/vscode_bodies.json"


def pick(s, arm):
    v = s[arm]
    return {k: v[k] for k in ("top1_accuracy", "escalated", "precision_when_routed")}


summer = json.load(SUMMER.open())
spring = json.load(SPRING.open())
raw = json.load(RAW.open())
bodies = json.load(BODIES.open())
titles = {r["number"]: r["title"] for r in raw}

out = {
    "result": {
        "summer": {"n": summer["summary"]["score"]["bot"]["issues"], "no_memory": pick(summer["summary"]["score"], "jev_nograph"),
                   "memory": pick(summer["summary"]["score"], "jev_graph"), "bot": pick(summer["summary"]["score"], "bot")},
        "spring": {"n": spring["summary"]["score"]["bot"]["issues"], "no_memory": pick(spring["summary"]["score"], "jev_nograph"),
                   "memory": pick(spring["summary"]["score"], "jev_graph_v2"), "bot": pick(spring["summary"]["score"], "bot")},
    }
}

# Replay sample: recorded summer HOLDOUT decisions, spread over time.
rows = collections.defaultdict(dict)
for r in summer["rows"]:
    if r["period"] == "holdout":
        rows[r["issue"]][r["arm"]] = r
issues = sorted((i for i, v in rows.items() if {"bot", "jev_nograph", "jev_graph"} <= set(v)), key=lambda i: rows[i]["bot"]["t"])
sample = issues[:: max(1, len(issues) // 40)][:40]
out["replay"] = [{
    "number": i, "title": titles.get(i, ""), "bot_pick": rows[i]["bot"]["bot_pick"], "owner": rows[i]["bot"]["truth"],
    "bot": rows[i]["bot"]["pick"], "no_memory": rows[i]["jev_nograph"]["pick"], "memory": rows[i]["jev_graph"]["pick"],
} for i in sample]

# Live examples: recent real issues the bot gave to people with rich handoff memory.
parsed = [parse_issue(r) for r in raw]
SENSITIVE = ("security", "vulnerab", "remote code", "exploit", "cve", "injection", "xss")


def ok(i):
    t = i.title.lower()
    return not any(w in t for w in SENSITIVE)

fwd = collections.Counter(h.from_login for i in parsed for h in derive_handoffs(i) if h.kind in ("forward", "reassign"))
rich = {p for p, n in fwd.items() if n >= 25}
ex = []
for star in ("benibenj", "pwang347"):  # the clearest handoff patterns in the data
    i = next(i for i in sorted(parsed, key=lambda i: -i.routing_time)
             if i.first_pick and i.first_pick.by == "vs-code-engineering" and i.first_pick.login == star and ok(i))
    ex.append({"number": i.number, "title": i.title, "body": (bodies.get(str(i.number)) or "")[:700], "proposed": star})
for i in sorted(parsed, key=lambda i: -i.routing_time):
    if i.first_pick and i.first_pick.by == "vs-code-engineering" and i.first_pick.login in rich and len(i.title) > 20 \
            and ok(i) and all(e["number"] != i.number for e in ex):
        if sum(1 for e in ex if e["proposed"] == i.first_pick.login) < 2:
            ex.append({"number": i.number, "title": i.title, "body": (bodies.get(str(i.number)) or "")[:700],
                       "proposed": i.first_pick.login})
    if len(ex) >= 9:
        break
# Order so the first three clicks show each behaviour (checked live on 2026-10-18):
# 341421 routes to a learned alternative, 341277 asks a human, 341245 keeps the bot's pick.
FIRST = [341421, 341277, 341245]
ex.sort(key=lambda e: FIRST.index(e["number"]) if e["number"] in FIRST else len(FIRST))
out["examples"] = ex

# Recorded real responses for every example, so the page isn't empty before the first click.
# Produced by the same route_issue the live API uses (local graph with the same data as the deployment).
from datetime import datetime, timezone
from handoff_graph.mcp_server import route_issue
day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
out["samples"] = {str(e["number"]): {"recorded_at": day, "response": route_issue(e["title"], e["body"], e["proposed"])}
                  for e in ex}
dest = ROOT / "src/handoff_graph/web/data.json"
json.dump(out, dest.open("w"), indent=1)
print("wrote", dest, "examples", [(e["number"], e["proposed"]) for e in ex])
