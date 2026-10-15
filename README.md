# Bounce Breaker

**An issue router that learns from every reassignment.** When a ticket bounces ("not me, ask @y"), Bounce Breaker remembers it in a FalkorDB graph. When the next similar ticket arrives, it routes it straight to the person who will own it and shows the graph path behind the decision. When it isn't sure, it asks a human instead of guessing.

Built for [Graph Hacks: Context for AI Agents](https://www.wemakedevs.org/hackathons/falkordb) (WeMakeDevs × FalkorDB).
Tracks: **Agents That Act on Connected Data** and **Agent Memory and Coordination**.

## The problem

- Reassigned incidents take up to 10× longer to triage at Microsoft (ICSE'19; DeepTriage, KDD'20).
- 37–44% of Mozilla and Eclipse bugs get tossed between developers (Jeong et al., FSE'09).
- Ticketing tools count reassignments, but none learns from *who handed what to whom*.

In **microsoft/vscode** (June to mid-October 2026):
- 11,734 issues were filed.
- 64% of first assignments came from the triage bot.
- 15% of assigned issues were handed off, and **72% of those handoffs followed the bot's pick**.

## Results

_Filled in from the one-time HOLDOUT run; see [docs/RESULTS.md](docs/RESULTS.md)._

## How it works

<!-- data model diagram, agents, Cypher, Jev decision rule -->

## Evaluation protocol

<!-- LEARN/TUNE/DEV/HOLDOUT, leakage rules, arms, disclosure -->

## Run it

```bash
docker run -d --name bb-falkordb -p 6380:6379 -p 3001:3000 falkordb/falkordb:latest
cp .env.example .env   # add TYPESAFE_API_KEY
uv sync
uv run python -m bounce_breaker.ingest data/raw/vscode_issues_2026-06-01_2026-10-15.json --bodies data/raw/vscode_bodies.json
uv run python -m bounce_breaker.replay --arms bot,graph,jev_nograph,jev_keep,jev_graph
uv run python -m bounce_breaker.mcp_server        # MCP over stdio
```

## Prior art

- Jeong, Kim & Zimmermann, *Improving Bug Triage with Bug Tossing Graphs* (FSE 2009)
- Microsoft DeepTriage (KDD 2020) and DeepCT (ASE 2019)
- Linear Triage Intelligence, Mozilla bugbug, ServiceNow Predictive Intelligence, and Prow's blunderbuss plugin

Bounce Breaker differs from these in four ways:
- it learns handoffs online, as they happen;
- it gives every decision with an explainable graph path;
- it escalates when unsure, using a confidence gate;
- it is scored with a leakage-safe, time-ordered replay against the deployed bot.

## AI assistance disclosure

This project was built with Claude Code (Anthropic) as a coding assistant. The author reviewed the design, data model, evaluation protocol and results, and is responsible for them.

## Data and licences

- Issue metadata comes from the public GitHub API for microsoft/vscode (MIT-licensed repository).
- People are shown by GitHub handle only. Findings describe team routing patterns, not individuals.
- The decision model is TypeSafe Jev, pinned to `jev-1.14.0`.
