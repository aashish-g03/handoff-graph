"""Load raw issue facts (issues, area labels, assignments) into FalkorDB.

Idempotent: everything is MERGEd on stable keys, so running it twice gives the same graph.
Learned handoff edges are NOT written here; the learner agent writes them as time advances.

    uv run python -m handoff_graph.ingest data/raw/vscode_issues_*.json [--bodies data/raw/vscode_bodies.json]
"""
from __future__ import annotations

import argparse
import json

from .db import QUERY_TIMEOUT_MS, get_graph
from .events import is_bot, parse_issue

BATCH = 500
OPEN = 9_999_999_999  # "not removed yet"; FalkorDB properties can't be null

SCHEMA = [
    "CREATE INDEX FOR (i:Issue) ON (i.number)",
    "CREATE INDEX FOR (p:Person) ON (p.login)",
    "CREATE INDEX FOR (a:Area) ON (a.name)",
    "CREATE INDEX FOR (i:Issue) ON (i.routing_time)",
]

UPSERT_ISSUES = """
UNWIND $rows AS r
MERGE (i:Issue {number: r.number})
SET i.title = r.title, i.body = r.body, i.created_at = r.created_at,
    i.routing_time = r.routing_time, i.state = r.state, i.author = r.author
"""

UPSERT_LABELS = """
UNWIND $rows AS r
MATCH (i:Issue {number: r.number})
MERGE (a:Area {name: r.area})
MERGE (i)-[l:HAS_LABEL {added_at: r.added_at}]->(a)
SET l.added_by = r.added_by, l.removed_at = r.removed_at
"""

UPSERT_ASSIGNMENTS = """
UNWIND $rows AS r
MATCH (i:Issue {number: r.number})
MERGE (p:Person {login: r.login})
SET p.bot = r.person_is_bot
MERGE (i)-[s:ASSIGNED {at: r.at}]->(p)
SET s.by = r.by, s.by_bot = r.by_bot, s.removed_at = r.removed_at, s.removed_by = r.removed_by
"""


def _batches(rows):
    for k in range(0, len(rows), BATCH):
        yield rows[k:k + BATCH]


def ensure_schema(g) -> None:
    for stmt in SCHEMA:
        try:
            g.query(stmt)
        except Exception as e:  # index already exists
            if "already" not in str(e).lower():
                raise


def ingest(raw_issues: list[dict], bodies: dict[str, str] | None = None, repo: str = "microsoft/vscode") -> dict:
    g = get_graph(repo)
    ensure_schema(g)
    bodies = bodies or {}
    issues = [parse_issue(r) for r in raw_issues]
    issue_rows, label_rows, assign_rows = [], [], []
    for i in issues:
        issue_rows.append({
            "number": i.number, "title": i.title, "body": bodies.get(str(i.number), ""),
            "created_at": i.created_at, "routing_time": i.routing_time, "state": i.state,
            "author": i.author or "",
        })
        for iv in i.labels:
            label_rows.append({
                "number": i.number, "area": iv.area, "added_at": iv.added_at,
                "added_by": iv.added_by or "", "removed_at": iv.removed_at or OPEN,
            })
        for a in i.assignments:
            assign_rows.append({
                "number": i.number, "login": a.login, "person_is_bot": is_bot(a.login), "at": a.at,
                "by": a.by or "", "by_bot": is_bot(a.by), "removed_at": a.removed_at or OPEN,
                "removed_by": a.removed_by or "",
            })
    for query, rows in ((UPSERT_ISSUES, issue_rows), (UPSERT_LABELS, label_rows), (UPSERT_ASSIGNMENTS, assign_rows)):
        for chunk in _batches(rows):
            g.query(query, {"rows": chunk}, timeout=QUERY_TIMEOUT_MS)
    return {"issues": len(issue_rows), "labels": len(label_rows), "assignments": len(assign_rows)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw")
    ap.add_argument("--bodies")
    ap.add_argument("--repo", default="microsoft/vscode")
    args = ap.parse_args()
    bodies = json.load(open(args.bodies)) if args.bodies else None
    print(ingest(json.load(open(args.raw)), bodies, args.repo))


if __name__ == "__main__":
    main()
