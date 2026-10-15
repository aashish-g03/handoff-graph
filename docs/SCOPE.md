# Bounce Breaker — Scope (v2, 2026-10-16, advisor-revised)

**One line:** an issue-routing agent for microsoft/vscode. It learns from every reassignment and routes the next similar issue straight to the person who ends up owning it. Each decision shows its graph path, and a confidence gate asks a human instead of guessing.

**Problem (verified):**
- Reassignment adds up to 10x to triage and mitigation time (Microsoft ICSE'19, DeepTriage KDD'20).
- 37–44% of bugs were reassigned in Mozilla and Eclipse (Jeong '09).
- Existing tools count reassignments but don't learn the sequence (ServiceNow community, 2025–26).
- First-hop "AI triage" is a commodity: about 18 Show HN launches with near-zero traction.
- Underserved: learning from the bounce, routing after the first hop, explaining and abstaining.

**Data evidence (VS Code, issues created 2026-06-01..10-15):**
- 11,734 issues; 18% of assigned issues were reassigned.
- 72% of reassignments followed the triage bot's first pick.
- In the top pairs, the first assignee forwards it themselves, e.g. 77/83 for benibenj -> mrleemurray, mostly 'modernization'.
- 72 person pairs recur 5+ times.
- Pitch wording: "skip the forwarding hop", not "the bot is wrong".

## Architecture
- **FalkorDB (core):** the ownership graph, learned handoffs, and the path behind every decision.
- **Decision layer:** TypeSafe **Jev** (the user has access). It makes a Choice over graph candidates and returns confidence; below the threshold, it escalates.
  - **Pin the model version.** Use `jev-1.14.0` explicitly, not `jev-latest`, which is moving to 1.14 within a week. Replay numbers must be reproducible. Record the version in the README.
  - **Keep state short.** The 1.14 post warns reliability drops on long inputs, so send the issue title, the first ~1,500 characters of the body and its labels. The graph does the narrowing. Don't use the long-context or image headers.
  - Fallback: Claude structured output.
  - OpenAI Decisions API: run a 60-second probe tonight. If it returns 403 it's out; if it works, compare it in the README on day 3 only.
- **LLM (Claude):** writes the explanation text only. It never writes Cypher.

## Graph schema (small on purpose)
- Nodes: `Issue`, `Person`, `Area` (VS Code feature labels), `Repo`
- Edges:
  - `(Issue)-[:LABELED {at, removed_at}]->(Area)`: TIMESTAMPED. Routing sees only the labels present at routing time; otherwise Jev picks the area from the text.
  - `(Issue)-[:ASSIGNED {at, by, bot}]->(Person)`, `(Issue)-[:UNASSIGNED {at}]->(Person)`
  - `(Person)-[:DEFERS_TO {topic, count, last_seen}]->(Person)`: learned from "A unassigned, B assigned". Self-claims are filtered out.
  - Activity and DEFERS_TO are computed **as of** routing time T: Cypher filters `WHERE e.at < $t` over the raw timestamped ASSIGNED/UNASSIGNED events. No static ACTIVE_IN (it would leak future ownership).
- **One graph per repo** (`select_graph(repo)`), i.e. FalkorDB multigraph as tenants.

## Must ship
1. Idempotent ingestion (MERGE on stable IDs, one command, run twice = same graph).
2. Three fixed tools, using parameterized Cypher and `ro_query` except the one write:
   - `resolve_issue_area`
   - `candidate_owners`: area -> active people -> apply DEFERS_TO -> drop inactive people; returns the path
   - `record_handoff`: the only write
3. Decision gate (Jev):
   - The pick must be in the candidate set.
   - Every handle in the prose must appear in the result rows.
   - Low confidence -> "ask @owner, because ...".
4. **Time-ordered replay harness**, which is also the test suite:
   - **Headline baseline = the REAL VS Code bot's recorded first pick** (64% of issues): "Microsoft's bot got the final owner right first time X%; our agent got Y% on the same issues."
   - Second baseline: Jev without the graph, which isolates the graph's contribution.
   - **Routing time T:** the bot's first-assignment timestamp, or issue creation.
   - **No leakage:** a handoff learned at time T only affects issues routed after T.
   - **Fair graph-off:** the same Jev call and issue text; candidates come from a plain area -> recent-assignee lookup, with no DEFERS_TO and no activity filter.
   - Metrics: top-1/top-3 vs the final owner, plus **NET forwarding hops avoided** (correct skips minus wrong skips where A actually kept the issue).
   - Report both the reassigned subset and all issues; show any regressions rather than hiding them.
   - Use the first 4–6 weeks as warm-up; choose the Jev confidence threshold there, not on the scored period.
   - The fallback (Claude) must also return a confidence value, so the gate still works.
5. **Two agents sharing state through FalkorDB:**
   - **Learner:** consumes the event stream; the only writer (`record_handoff`).
   - **Router:** read-only.
   - Plus an MCP server exposing the tools (thin wrapper).
6. Deploy: FalkorDB Cloud (password) + a small server on Fly or Render; Docker Compose locally.
7. README:
   - data model diagram
   - the actual Cypher
   - numbers plus caveats
   - prior art: Jeong'09, DeepTriage, Linear Triage Intelligence, Mozilla bugbug, Prow blunderbuss
   - AI-use disclosure
   - VS Code (MIT) attribution
8. Demo video (beat 1: replay with a live counter; beat 2: one handoff changes the next route) + a short blog post.

## Nice-to-have (cut from the bottom)
1. Live polling of new VS Code issues as a second demo beat
2. A minimal path-viewer UI
3. OpenAI Decisions comparison
4. Kubernetes OWNERS as a second dataset
5. Per-user/tenant graphs beyond one demo tenant

## Out of scope (don't let these creep back)
- Helpdesk/ITSM routing (a different problem; mention only as "same approach applies")
- HR anything (stays clear of the employer's product)
- A general "who do I ask" chat
- LLM extraction of files from issue bodies

## Tracks
- **Track 1:** multi-hop routing, path returned, algorithms as tools.
- **Track 2:** handoff memory learned online that changes behaviour.
- **Track 3:** only if ownership/expertise is genuinely on screen; otherwise enter two tracks.

## Ethics / framing
- Present findings as team routing patterns, never as judgements of individuals.
- Show handles only in the video; use pseudonyms in the blog.

## Open checks
- FalkorDB `algo.pageRank` has no personalization; use a traversal score, and claim PageRank only if it's actually run.
- Jev's exact request format and limits: verify from the docs/SDK on day 1.

## Timeline (deadline Oct 18 11:59 PM IST)
- **Oct 16 (tonight):** repo + Docker, schema, ingestion, `candidate_owners` returning a path for one real issue, OpenAI probe.
- **Oct 17:** DEFERS_TO learning + replay harness + **measured A/B numbers (gate)**; Jev gate; MCP; deploy skeleton.
- **Oct 18:** feature freeze at noon IST; deploy, README, video, blog, submit.
