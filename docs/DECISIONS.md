# Decisions log: why Handoff Graph is built the way it is

Each entry gives **what we decided**, **why**, **what we rejected**, and **what it cost us**. The entries are in the order the decisions were made, so you can follow how the project changed shape.

---

## Part A: Choosing the idea

### D1. Solve a problem people recognise, not an exotic one
- **Decided:** route tickets to the right person and learn from "not me, ask @y" handoffs.
- **Why:** reviewers and other models kept arriving at "tickets bounce between teams" on their own. Research shows it's costly: reassignment adds up to 10× triage time at Microsoft (ICSE'19, DeepTriage).
- **Rejected (and why):**
  - **Retracted-paper contamination:** strong data, but a domain the author couldn't defend in front of judges.
  - **Stale Stack Overflow guard:** linters already catch these, and the graph wasn't essential.
  - **Transit-visa agent:** the hero example was legally wrong, and it was really a rule table.
  - **HR career paths:** too close to the author's employer's product.
  - **Memory layer for coding agents:** a crowded category.
- **Cost:** ticket routing is a familiar idea, so clone density is medium.

### D2. Use microsoft/vscode as the dataset
- **Decided:** public VS Code issues, June – October 2026, about 11.7k issues.
- **Why:** we measured several active repos.

  | Repo | Share of issues reassigned |
  |---|---|
  | VS Code | **16%** |
  | Next.js | 0% |
  | PyTorch | 1% |
  | Rust | 1% |

  VS Code also has a **triage bot** whose first picks are recorded, which gives a real, non-straw-man baseline.
- **Rejected:**
  - **Kubernetes:** bounces never repeated, so there was nothing to learn.
  - **Mozilla Bugzilla:** good data, but an older project.
- **Cost:** all evidence comes from one repo and one team.

---

## Part B: Architecture

### D3. FalkorDB graph as the agent's memory, one graph per repo
- **Decided:** store issues, people, areas, assignments and **HANDED_OFF** edges in FalkorDB, in a graph named `hg:<owner>:<repo>`.
- **Why:**
  - Who handed what to whom is naturally a graph: Person → Person edges with timestamps.
  - It answers queries like "who does A usually pass work to, recently?"
  - FalkorDB holds many isolated graphs in one instance, so one graph per repo keeps tenants apart.
- **Rejected:** a flat table of (from, to, count). It loses the issue-level evidence and the timestamps needed for "as of time T."

### D4. Two agents: a learner (only writer) and a router (read-only)
- **Decided:** `learner.py` writes HANDED_OFF edges; `router.py` and `agent.py` only read.
- **Why:**
  - It makes "agents share state through the graph" (Track 2) literally true.
  - It makes leakage easy to prevent, because the router can't accidentally write future knowledge.

### D5. The model never writes Cypher
- **Decided:** a fixed set of tools over parameterised queries (`ro_query` everywhere except the learner).
- **Why:**
  - LLM-generated queries can be wrong, expensive or injectable.
  - The organisers' own tutorial recommends this pattern.

### D6. TypeSafe Jev as the decision layer, not a chat LLM
- **Decided:** Jev answers narrow typed questions:
  - a **Noul** (yes/no probability) per candidate;
  - a **Score** for "keep vs hand off";
  - a **Choice** as a tie-breaker.
- **Why:**
  - Jev returns **calibrated probabilities and confidence** instead of prose, so code can combine and threshold them.
  - It takes about 0.35 s and costs well under $0.0001 per decision.
  - The user already had access.
- **Rejected:**
  - **OpenAI Decisions API:** access was unclear and no schema was published.
  - **A chat LLM:** it can't be thresholded reliably.
- **Details:**
  - The model is pinned to `jev-1.14.0`, because the `jev-latest` alias moves.
  - Inputs are kept short (title plus 1,500 characters of the body), because Jev's docs warn that long, noisy inputs hurt accuracy.
  - Candidate order is shuffled for the Choice question, because Jev leans toward the first option.

### D7. The graph decides *who could* own it; Jev decides *which one*
- **Decided:** the graph produces up to 5 candidates plus a **prior** (how often A keeps vs passes on). Jev supplies per-candidate **likelihoods** from the text. Code multiplies them.
- **Why:** Jev's docs say it's weak at multi-hop reasoning, while graphs are good at it. Each part does what it's good at.
- **Rule** (fixed in code before results were seen):
  `posterior ∝ prior × likelihood`. Then tie-break if close, and escalate if still unsure.

### D8. Show contrastive evidence: "what A kept" vs "what A handed to B"
- **Decided:** each candidate's evidence for Jev comes from the graph's memory: titles of issues A kept, and titles of issues A handed to B.
- **Why:** the first version showed "everything B owns," and Jev's signal was too weak to matter. The contrastive version is the graph doing real work.

### D9. Escalate to a human instead of guessing
- **Decided:** if the decision isn't clear, return "ask a human" with the reason.
- **Why:** a wrong route costs a bounce. Jev's docs describe "confidence-gated routing" as the intended pattern.

### D10. Deployment: FalkorDB Cloud (free) + Railway (Docker) + MCP over HTTP
- **Decided:** the summer graph goes to FalkorDB Cloud, with bodies trimmed to fit 19 MB of the 100 MB free tier. The MCP server runs on Railway.
- **Why:**
  - The user had Railway Pro, so there are no cold starts.
  - Railway deploys from the local folder, so no GitHub push was needed.
  - MCP lets any AI coding tool use the router.
- **Rejected:**
  - **Render:** its free tier sleeps.
  - **Putting the spring graph in the cloud:** it's evaluation-only, and the two graphs together would be close to the 100 MB limit.

---

## Part C: Evaluation (the most important decisions)

### D11. A time-ordered replay against the real bot
- **Decided:** walk through history in order. Route each issue at the moment the bot first assigned it, and score it against who owned it at the end.
- **Why:** it's the only fair test, and it compares against what Microsoft actually runs.

### D12. No peeking into the future (leakage rules)
- Every router query filters `at < T`.
- The learner advances one day at a time.
- Labels added after T are invisible; `HAS_LABEL` carries timestamps.
- Truth must have had **30 or more days to settle**, so issues routed after Sep 15 aren't scored.
- **Why it mattered:** we found that only 389 of 1,937 handoffs had an area label at handoff time. An earlier "61 times on modernization" figure used labels added later, and we discarded it.

### D13. A fair baseline: same decision code, no graph
- **Decided:** the "Jev, no graph" arm calls the *same* `decide()` function, with a plain "recently active people" candidate list. There's also a "Jev keep-check" control.
- **Why:** otherwise we'd be measuring prompt wording, not the graph.

### D14. Freeze the design, then test once on unseen data
- **Periods:**
  - **LEARN:** memory only.
  - **TUNE:** thresholds only.
  - **DEV:** all design work.
  - **HOLDOUT:** run once.
- **Why:** after looking at results twice, any further change tested on the same data would be fooling ourselves.
- **Disclosed:** two early designs were looked at before the split.

### D15. Fixing the probability model (v1 prior)
- **Found:** the first graph scoring ignored that A **keeps most** issues, so it overrode the bot far too often (57% vs 79%).
- **Fixed:** P(stays with A) = kept/received. This is a model correction, not tuning; it's recorded as such.

### D16. Memory trust rule
- **Decided:** use contrastive Jev only if A has **10 or more** recorded forwards before T; otherwise keep the bot's pick.
- **Why:** with little memory, the evidence is noise. The threshold comes from pre-T data only.

### D17. Trying to beat the bot (v2), with a pre-registered win condition
- **Decided:**
  - a 60-day memory window, because DEV showed patterns drift;
  - three outcomes: route / escalate / keep;
  - **win = precision when routed ≥ bot + 2 points, with ≤ 15% escalated**, written down before fetching new data.
- **Fresh holdout:** Jan–May 2026, fetched separately, with its own graph, run once.
- **Result:** +3.8 points on DEV, but **+0.5 on the fresh holdout. Not met.** Reported as such.

### D18. Report honestly, and lead with what replicated
- **Decided:** the headline is "memory makes the agent usable," which replicated on both holdouts. "Doesn't beat the bot" sits on the first screen too.
- **Why:** judges trust a result more when the limitations are stated next to it.

---

## Part D: Product and naming

### D19. Name: Handoff Graph
- **Why:** it says exactly what it is, promises no result, and puts "Graph" in front of FalkorDB judges.
- **Rejected:**
  - **Bounce Breaker:** it overpromised once the holdout showed no bounce reduction.
  - **Baton, Wayfinder:** already taken by other tools.

### D20. Track: Agent Memory and Coordination
- **Why:**
  - The organisers confirmed a project can be listed for many tracks but wins only one.
  - Our strongest replicated result is about memory.
  - Learner and router coordinate through shared graph state.
  - Memory is isolated per repo.

### D21. Honest limits to state, not hide
- It doesn't beat VS Code's bot on first-try accuracy.
- The evidence comes from one repo.
- It only helps where reassignments are common.
- The forwarding signal is mostly not in the text (pooled AUC 0.57).
- Memory goes stale within weeks.
