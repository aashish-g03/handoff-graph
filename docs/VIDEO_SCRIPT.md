# Demo video script: Handoff Graph (about 2 minutes 40 seconds)

**Track:** Agent Memory and Coordination.
**The one idea to land:** the same AI behaves differently because of graph memory. It routes, keeps the current owner, or asks a human, and it shows the graph path behind each decision.

Everything on camera is the live page, https://handoff-graph.up.railway.app/, plus one FalkorDB Browser shot. You don't need a terminal or a Claude Code session.

## Before recording

- **Screen:** 1920×1080 at 125–150% browser zoom, other tabs closed. Shot 2 carries the video, so the path chip must be readable.
- **Rate limit:** live routing allows 60 requests per minute per visitor (and 360 per minute in total).
  - Do one warm-up route at least a minute before you start recording.
  - Don't rehearse the three clicks again in the minute before a take, or the third click can be refused on camera.
- **Check the three examples right before recording** (last checked live 2026-10-18):

  | Issue | Triage bot's pick | Expected live result |
  |---|---|---|
  | #341421, "WSL Webview resources return 401…" | @aeschli | **Route to @connor4312** (path: @aeschli handed 5 of 151 to @connor4312) |
  | #341277, Copilot instruction/skill quality check | @pwang347 | **Ask a human** ("too close to call") |
  | #341245, "API: let extensions open an editor in a new floating window…" | @benibenj | **Keep @benibenj** (kept 238 of 405) |

- **FalkorDB Browser (Shot 3):**
  - Open http://localhost:3001 and log in with host `localhost`, port `6379` (the Browser runs inside the container, so use the inner port, not 6380). Leave username and password empty.
  - Select graph `hg:microsoft:vscode`; its memory holds about 2,000 `HANDED_OFF` edges.
  - Paste the query below and run it once before recording, so the layout settles:
  ```cypher
  MATCH (a:Person {login:'benibenj'})-[h:HANDED_OFF]->(b:Person)
  RETURN a, h, b LIMIT 60
  ```

---

## Shot 1: The problem (0:00–0:15)
**Screen:** the page hero, without scrolling.

> "Every engineering team knows this ticket: it's assigned to you, it isn't yours, and you pass it on. In VS Code, 1,678 issues were handed on like that in four and a half months, four out of five right after the triage bot's pick. Every handoff is knowledge, *this kind of issue goes to that person*, and nobody keeps it. Handoff Graph does."

## Shot 2: Three issues, three behaviours (0:15–0:55)
**Screen:** the hero's issue list (left) and the console (right). Click each issue, then press **Route this issue**. Wait for the live answer: the "Recorded answer from…" note disappears when the live result arrives.

1. **#341421.** The bot picked @aeschli.
   > "The bot would give this WSL webview bug to aeschli. The graph remembers that aeschli has handed issues like this to connor4312 before, and Jev agrees the text fits. So it routes straight to connor4312, and here's the path: aeschli handed 5 of 151 to connor4312, with the issue numbers."
   Point at the path chip.
2. **#341277.**
   > "This one is too close to call. Memory says pwang347 often passes work on, but the text doesn't settle where it should go. So instead of guessing, it asks a human and says why."
3. **#341245.**
   > "And here memory says benibenj keeps issues like this: 238 of 405. So it leaves the bot's pick alone."

> "Same agent, three different decisions, and each one is justified by a path in the graph."

## Shot 3: What's underneath (0:55–1:25)
**Screen:** FalkorDB Browser with the query above. Optionally finish on the page's **What the memory knows** section with `benibenj` selected (hawkticehurst 76, mrleemurray 65; the explorer counts every handoff kind, the routing path counts forwards only).

> "This is the memory, in FalkorDB. Every reassignment becomes a timestamped HANDED_OFF edge between two people. Two agents share this graph. The learner is the only one that writes: it records each handoff as it happens. The router only reads, and only what was true before the issue arrived. Every query filters on the edge's timestamp, so a decision can never see the future. Each repository gets its own graph. The model never writes Cypher. It gets a fixed set of tools over parameterised queries."

## Shot 4: The result (1:25–1:55)
**Screen:** press ⌘K, choose **Results**, and land on the dark band.

> "We tested this on real VS Code triage, replayed in time order, on two periods the system never saw during development, each run once with a frozen design. Same AI model, same decision code, with and without graph memory.
> Without memory, it gives up and hands 66% of issues to a human. With memory, 4%.
> Right owner on the first try: 18% without memory, 74% with it. Microsoft's dedicated triage classifier, built for this one repo, gets 77%.
> The spring period replicates it: 64% down to 7%, and 15% up to 58%, against the classifier's 62%."

Point at each number as you say it.

## Shot 5: What it doesn't do (1:55–2:25)
**Screen:** scroll to **What it doesn't do**.

> "It doesn't beat that classifier on a single first guess, and we checked why. Even perfect knowledge of which issues get forwarded tops out near 85%. Most handoffs depend on workload and absences you can't see when an issue arrives. And memory about people goes stale fast: the memory's best alternative named the right owner 38% of the time in July and August, and 13% a month later. That's why the learner keeps learning from every new handoff."

## Shot 6: Use it, and the end card (2:25–2:40)
**Screen:** the README's MCP section on GitHub, then the end card.

> "It's also a live MCP server with three tools, so Claude Code or any MCP client can route issues with it. Everything is open source, with the replay data, so you can reproduce every number."

```bash
claude mcp add --transport http handoff-graph https://handoff-graph.up.railway.app/mcp
```

**End card:**
- https://handoff-graph.up.railway.app
- github.com/aashish-g03/handoff-graph
- "Built with FalkorDB + TypeSafe Jev · Graph Hacks 2026 · Track: Agent Memory and Coordination"

---

### Numbers used on camera (sources: docs/RESULTS.md and the live page)
- 1,678 handed-off issues (16.1% of assigned); 79.3% started with the bot's pick.
- Asks a human, without → with memory: summer 66.5% → 3.7% (shown as 66% → 4%); spring 64.5% → 6.6% (64% → 7%).
- Right first time, without → with memory, with the classifier for scale:
  - summer 18.4% → 74.3%, vs 76.9%;
  - spring 15.0% → 58.5%, vs 62.1% (shown as 18% → 74% vs 77%, and 15% → 58% vs 62%).
- Ceiling (development data): 85.1% vs the bot's 77.8%.
- Drift: the memory's best alternative was right on 38% of bounced issues on development data vs 13% on the summer held-out period.
- The live server runs the v1 design (the summer numbers).
