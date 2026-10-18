# Demo video script: Handoff Graph (about 2.5 minutes)

**Track:** Agent Memory and Coordination.
**One idea to land:** graph memory is what makes the agent usable, and we show honestly where it stops.

## Before recording
- Use a terminal font of 18pt or larger, a dark theme, a window at least 120 columns wide, and the repo as the working directory.
- FalkorDB Browser: open `http://localhost:3001` (local) (the live demo database runs on Railway, private network only). Log in and open graph `hg:microsoft:vscode`.
- In Claude Code, add the hosted MCP server once:
  ```bash
  claude mcp add --transport http handoff-graph https://handoff-graph.up.railway.app/mcp
  ```
  Then run `/mcp` and check that `handoff-graph` shows 3 tools.
- Do a warm-up call before recording (Shot 4's prompt), so the first live call isn't the cold one.

---

## Shot 1: The problem (0:00–0:20)
**Screen:** README top section, or a slide with the VS Code numbers.

> "Every engineering team knows this ticket: it's assigned to you, it isn't yours, and you pass it on. In VS Code alone, almost 1,700 issues were handed off in four and a half months, and four out of five of them started with the triage bot's pick. Every handoff is knowledge: *this kind of issue goes to that person.* Nobody keeps it."

## Shot 2: How it works (0:20–0:45)
**Screen:** the README's mermaid diagram. Then FalkorDB Browser running:
```cypher
MATCH (a:Person {login:'benibenj'})-[h:HANDED_OFF]->(b:Person)
RETURN a, h, b LIMIT 60
```
> "Handoff Graph has two agents that share one FalkorDB graph. A learner agent turns every reassignment into a timestamped HANDED_OFF edge; it's the only one that writes. A router agent reads that memory as of the moment a new issue arrives. It asks TypeSafe Jev one narrow question per candidate: does this issue look like what this person kept, or what they passed on? Then it routes, keeps the current owner, or asks a human. Each repository gets its own graph."

## Shot 3: Same model, with and without memory (0:45–1:30)
**Screen:** terminal.
```bash
uv run python -m handoff_graph.demo results/replay_20261015T203103Z.json --n 25 --delay 0.6
```
> "This is a replay of real VS Code triage on issues the system never saw during development. These are the recorded decisions, not recomputed. Green is right, red is wrong, yellow means it asked a human.
> Without graph memory, the same model and the same decision code has to ask a human about two-thirds of the time. With memory, about one in twenty-five here. Same model, same code. The only difference is the context layer."

Pause on the final summary block. Point at **asks a human: 66.5% → 3.7%**.

## Shot 4: Live, from Claude Code (1:30–2:05)
**Screen:** Claude Code.
**Prompt:**
> Use handoff-graph to route this new VS Code issue. The triage bot would assign it to benibenj. Title: "Tab titles render with no text in the new modern UI". Body: "After enabling the new modern workbench UI, editor tab titles appear blank until hovered. macOS."

> "Here's the hosted MCP server: Railway, FalkorDB on Railway, Jev. It names an owner, gives a probability for every candidate, and for each one the graph path behind it: benibenj handed 75 of 405 such issues to hawkticehurst, with the issue numbers. The model never writes a query. It gets a fixed set of tools over parameterised Cypher."

Optional, if there's time: ask *"Who does pwang347 usually hand issues to?"* to show `handoff_history`.

## Shot 5: The result, honestly (2:05–2:30)
**Screen:** the README "The result" table.
> "So here's the result. The same AI, with and without memory. Without the graph it has to hand two-thirds of issues to a human. With FalkorDB memory, about one in twenty. When it does route, it's about as accurate as Microsoft's dedicated triage classifier on the same issues, and within a few points of it on the first guess, with no training and no per-repo model. It doesn't beat that classifier on a single first guess, and we tested why: what decides most handoffs isn't visible when an issue arrives. And memory about people goes stale within weeks, so it has to keep learning. Handoff Graph does, and it shows its reasoning every time."

**End card:** repo URL, MCP URL, "Built with FalkorDB + TypeSafe Jev · Graph Hacks 2026".

---

### Numbers used on camera, all from docs/RESULTS.md
- 1,678 handed-off issues (16.1% of assigned); 79.3% started with the bot's pick. Source: `events.derive_handoffs` over the full Jun 1 – Oct 15 pull.
- Summer held-out escalation: no graph 66.5% (rounds to 66%); with graph 3.7%.
- Spring held-out escalation: no graph 64.5%; with graph 6.6%.
- Right first time: summer 74.3% vs bot 76.9%; spring 58.5% vs bot 62.1%.
- Memory-alternative hit rate on bounced issues: 38% (DEV) vs 13% (summer HOLDOUT).
