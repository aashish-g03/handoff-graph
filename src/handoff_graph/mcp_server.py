"""MCP server: lets any MCP client (Claude Code, Cursor, ...) route issues with Handoff Graph.

Tools are a fixed catalogue over parameterised Cypher; the model never writes queries.

    uv run python -m handoff_graph.mcp_server                 # stdio
    uv run python -m handoff_graph.mcp_server --http 8765     # streamable HTTP
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .agent import ROUTING_GATE
from .agent import route_issue as _route
from .db import QUERY_TIMEOUT_MS, get_graph
from .decide import JevJudge
from .events import Handoff
from .learner import record_handoffs

mcp = MCPServer("handoff-graph")
_judge: JevJudge | None = None


def _jev() -> JevJudge:
    global _judge
    if _judge is None:
        _judge = JevJudge()
    return _judge


def _person_exists(g, login: str) -> bool:
    return bool(g.ro_query("MATCH (p:Person {login: $l}) RETURN p.login", {"l": login},
                           timeout=QUERY_TIMEOUT_MS).result_set)


@mcp.tool()
def route_issue(title: str, body: str, proposed_assignee: str, repo: str = "microsoft/vscode") -> dict:
    """Decide who should own a new issue that the current process would assign to `proposed_assignee`.

    Returns the chosen owner (or an escalation), the confidence margin, every candidate's probability,
    and the graph path behind each candidate. Uses only handoffs recorded so far.
    """
    g = get_graph(repo)
    if not _person_exists(g, proposed_assignee):
        return {"owner": None, "escalate": True,
                "reason": f"@{proposed_assignee} is not in the {repo} graph; not modelled, ask a human"}
    r = _route(g, _jev(), {"number": -1, "title": title, "body": body}, int(time.time()), proposed_assignee)
    d = r.decision
    return {
        "owner": d.owner,
        "escalate": d.owner is None,
        "reason": d.reason,
        "margin": round(d.margin, 3),
        "gate": ROUTING_GATE,
        "memory_trusted": r.memory_trusted,
        "candidates": [
            {"login": c, "probability": round(d.posterior.get(c, r.prior.get(c, 0.0)), 3), "path": r.paths.get(c, "")}
            for c in sorted(r.candidates, key=lambda c: -d.posterior.get(c, r.prior.get(c, 0.0)))
        ],
        "jev_calls": d.jev_calls,
    }


@mcp.tool()
def handoff_history(person: str, repo: str = "microsoft/vscode", limit: int = 10) -> list[dict]:
    """Who has `person` handed issues to, how often, and example issues (graph memory, read-only)."""
    g = get_graph(repo)
    rows = g.ro_query(
        "MATCH (:Person {login: $p})-[h:HANDED_OFF]->(b:Person) "
        "WITH b, count(h) AS times, collect(h.issue)[0..5] AS examples "
        "RETURN b.login, times, examples ORDER BY times DESC LIMIT $k",
        {"p": person, "k": limit}, timeout=QUERY_TIMEOUT_MS).result_set
    return [{"to": b, "times": n, "example_issues": ex} for b, n, ex in rows]


@mcp.tool()
def record_handoff(issue_number: int, from_person: str, to_person: str, repo: str = "microsoft/vscode") -> str:
    """Learner write: remember that `from_person` handed `issue_number` to `to_person` (e.g. "not me, ask @y")."""
    if os.getenv("HG_ALLOW_WRITES") != "1":
        return "writes are disabled on this server (set HG_ALLOW_WRITES=1 on a private deployment)"
    g = get_graph(repo)
    for login in (from_person, to_person):
        g.query("MERGE (p:Person {login: $l}) ON CREATE SET p.bot = false", {"l": login}, timeout=QUERY_TIMEOUT_MS)
    record_handoffs(g, [Handoff(issue_number, from_person, to_person, int(time.time()), from_person,
                                "forward", False, ())])
    return f"remembered: @{from_person} -> @{to_person} for #{issue_number}"


# ---------------- Public web page + JSON API (same service as /mcp) ----------------
WEB = Path(__file__).parent / "web"
_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()
PER_IP_PER_MIN, GLOBAL_PER_MIN = 6, 60


def _allowed(ip: str) -> bool:
    """Small in-memory rate limit for live routing (each call spends Jev tokens)."""
    now = time.time()
    with _hits_lock:
        for key, cap in ((ip, PER_IP_PER_MIN), ("*", GLOBAL_PER_MIN)):
            q = _hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= cap:
                return False
        _hits[ip].append(now)
        _hits["*"].append(now)
    return True


def _json(data, status: int = 200):
    from starlette.responses import JSONResponse
    return JSONResponse(data, status_code=status)


@mcp.custom_route("/", methods=["GET"])
async def page(request):
    from starlette.responses import HTMLResponse
    return HTMLResponse((WEB / "index.html").read_text())


@mcp.custom_route("/api/data", methods=["GET"])
async def api_data(request):
    return _json(json.loads((WEB / "data.json").read_text()))


@mcp.custom_route("/api/people", methods=["GET"])
async def api_people(request):
    g = get_graph()
    rows = g.ro_query("MATCH (a:Person)-[h:HANDED_OFF]->() WHERE h.kind IN ['forward','reassign'] "
                      "WITH a, count(h) AS n WHERE n >= 10 RETURN a.login, n ORDER BY n DESC",
                      timeout=QUERY_TIMEOUT_MS).result_set
    return _json([{"login": login, "handoffs": n} for login, n in rows])


@mcp.custom_route("/api/history", methods=["GET"])
async def api_history(request):
    person = (request.query_params.get("person") or "")[:64]
    return _json(handoff_history(person, limit=6))


@mcp.custom_route("/api/route", methods=["POST"])
async def api_route(request):
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0]
    if not _allowed(ip):
        return _json({"error": "Too many live requests. Wait a minute and try again."}, 429)
    try:
        body = await request.json()
        title = str(body.get("title", ""))[:300].strip()
        text = str(body.get("body", ""))[:3000]
        who = str(body.get("proposed_assignee", ""))[:64].strip().lstrip("@")
    except Exception:
        return _json({"error": "Send JSON with title, body and proposed_assignee."}, 400)
    if not title or not who:
        return _json({"error": "A title and a proposed assignee are required."}, 400)
    import anyio
    return _json(await anyio.to_thread.run_sync(lambda: route_issue(title, text, who)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", type=int, default=None, help="serve streamable HTTP on this port")
    a = ap.parse_args()
    if a.http:
        mcp.run(transport="streamable-http", host="0.0.0.0", port=a.http)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
