---
title: "Same AI, with and without memory: a FalkorDB graph took issue routing from 18% to 74%"
published: false
description: "Handoff Graph remembers who hands which GitHub issues to whom. Tested on 4,197 real VS Code issues the system never saw, graph memory cut 'ask a human' from 66% to 4%."
tags: graphhacks, falkordb, wemakedevs, ai
cover_image: https://raw.githubusercontent.com/aashish-g03/handoff-graph/main/docs/blog/cover.png
---

> **TL;DR:** Handoff Graph is an issue-routing agent that remembers **who hands which issues to whom** in a FalkorDB graph. I tested the same AI model and the same decision code with and without that memory, on two held-out periods of **real microsoft/vscode triage** (4,197 issues), each run once. In the summer period, without memory it hands **66%** of issues to a human and picks the right owner first time **18%** of the time. With memory: **4%** and **74%** (spring is similar: 64% to 7%, and 15% to 58%), within a few points of Microsoft's purpose-built triage classifier, with no training. It does **not** beat that classifier, and I show why.
>
> [Live demo](https://handoff-graph.up.railway.app) (no sign-up) | [Code](https://github.com/aashish-g03/handoff-graph) | [MCP server](https://handoff-graph.up.railway.app/mcp) | Built for Graph Hacks (WeMakeDevs x FalkorDB), Track 2: Agent Memory and Coordination

{% embed VIDEO_URL %}

---

## "Not me, ask them"

A ticket is assigned to you, it isn't yours, and you pass it on. Every engineering team does this many times a week. Microsoft's own research found that reassigned incidents can take up to 10× longer to triage. A 2009 study of Mozilla and Eclipse found that 37 to 44% of bugs got passed between developers. Ticketing tools count these reassignments, but they don't learn from them.

I used **microsoft/vscode** because it's very active and its triage is public. Between June and mid-October 2026, 11,734 issues were filed. A triage bot made 65% of the first assignments. 1,678 issues were handed on to someone else, and four out of five of those handoffs started with the bot's pick.

Each of those handoffs carries knowledge: *this kind of issue, given to this person, ends up with that person.* Some engineers act as hubs. One engineer (call them A) received 405 issues from the bot between June and October, kept 238, handed 75 to one colleague and 64 to another. That pattern is invisible in any single issue, and obvious in a graph:

![One engineer's handoff memory in FalkorDB: of 405 issues the bot gave them, they kept 238, handed 75 to B, 64 to C, and a few to others](https://raw.githubusercontent.com/aashish-g03/handoff-graph/main/docs/blog/memory-v2.png)

The hackathon's tagline is "agents are only as good as the context they work with." I wanted to measure that claim instead of asserting it. Routing is a good test, because an agent has to make the same decision thousands of times, and history says who was right.

## What I built

![Architecture: a learner agent writes HANDED_OFF edges into FalkorDB; a read-only router agent reads memory as of time t, asks Jev one question per candidate, then routes, asks a human, or keeps the bot's pick](https://raw.githubusercontent.com/aashish-g03/handoff-graph/main/docs/blog/architecture-v2.png)

**Handoff Graph** has two agents that share one FalkorDB graph.

- **The learner** turns every reassignment event into a timestamped edge, `(:Person)-[:HANDED_OFF {issue, at, kind}]->(:Person)`. It's the only component that writes.
- **The router** is read-only. When an issue arrives for the bot's pick A, it asks the graph who A has handed similar work to, and how often A kept it. That gives it a short candidate list and a prior. Then it asks a decision model, [TypeSafe Jev](https://docs.typesafe.ai), one narrow yes/no question per candidate: does this issue look like the ones A kept, or the ones A passed to B?
- **The decision rule lives in code, not in a prompt.** If an alternative clearly wins, route to them. If it's too close to call, ask a human and say why. Otherwise, keep the bot's pick.

Every decision comes back with the graph path that justifies it. Here's the live page making a real call. The bot would give this WSL bug to one engineer; memory says that engineer has passed issues like it to a colleague, and the text agrees:

![The live demo routing a real VS Code issue: the bot's pick handed 5 of 151 similar issues to another engineer, so the agent routes there, showing every candidate's probability and evidence issues](https://raw.githubusercontent.com/aashish-g03/handoff-graph/main/docs/blog/live-route-v2.png)

*(The live demo shows public GitHub handles because every path cites public issues. This post uses letters instead.)*

The model never writes Cypher. It gets a fixed set of tools over parameterised queries, exposed through an MCP server, so Claude Code or any MCP client can call it. Each repository gets its own graph. The core query is small, and its one important detail is the timestamp filter:

```cypher
MATCH (a:Person {login: $first_pick})-[h:HANDED_OFF]->(b:Person)
WHERE h.at < $t AND h.at >= $since AND h.kind IN ['forward', 'reassign']
WITH b, count(h) AS times, max(h.at) AS last_at,
     collect(h.issue)[0..5] AS examples
RETURN b.login AS login, times, last_at, examples
ORDER BY times DESC, last_at DESC
```

## How I measured it

Honestly, most of my time went here. It's easy to fool yourself on a task like this.

![Evaluation timeline: summer data split into learn, tune, develop and a held-out period run once; spring data in its own graph with learn, tune and a held-out period run once](https://raw.githubusercontent.com/aashish-g03/handoff-graph/main/docs/blog/protocol-v2.png)

- **Time-ordered replay.** Each historical issue is routed at the exact moment VS Code's bot first assigned it. The learner advances day by day, and every router query filters `at < $t`, so a decision can never see a later handoff.
- **No label leakage.** VS Code issues gain area labels over time, often from the same person who later reassigns them. Only about one handoff in five had an area label at the moment of routing. So the router only sees labels that existed at that moment, and otherwise relies on the issue text.
- **A fair comparison.** "Without memory" means the *same* Jev model and the *same* decision code. Only the candidates and prior come from somewhere else: the people most often assigned in the previous two weeks.
- **Frozen design, held-out data, run once.** I did all design work on a development window. Then I froze the design, committed the exact command, and ran it once on a held-out period (summer: Aug 25 to Sep 15, 1,133 issues). Later I fetched a second, completely separate period (spring: Apr 1 to May 15, 3,064 issues), built its own graph and ran it once too.

## The result

![Results: without graph memory the agent asks a human 66% and 64% of the time; with memory 4% and 7%. Right owner first time rises from 18% and 15% to 74% and 58%, against VS Code's classifier at 77% and 62%](https://raw.githubusercontent.com/aashish-g03/handoff-graph/main/docs/blog/results-v2.png)

| Same model, same decision code | Has to ask a human | Right owner, first try |
|---|---|---|
| Without graph memory | 66% / 64% | 18% / 15% |
| **With FalkorDB graph memory** | **4% / 7%** | **74% / 58%** |
| VS Code's dedicated triage classifier, for scale | 0% | 77% / 62% |

*(summer / spring)*

Without memory, the agent is nearly useless. It hands two-thirds of issues to a human, and it picks the right owner first time less than one time in five. With memory, it asks for help on about one issue in twenty, and its first-try accuracy lands within 2 to 4 points of Microsoft's purpose-built classifier. That classifier runs on its own model with a hand-maintained ownership file, and the VS Code team corrects it by hand. Mine has no training and no per-repo model. Both held-out periods tell the same story.

## Is FalkorDB doing real work?

The hackathon's rules say the graph has to do real work, and this is the cleanest test I could design for it: take the graph away and keep everything else the same. Same model, same prompts, same decision code. What collapses is exactly what the graph provides: who handed what to whom, as of that moment. Escalations go from 4% to 66%, and first-try accuracy goes from 74% to 18%.

How the project maps onto Track 2:

| Track 2 asks for | In Handoff Graph |
|---|---|
| Persistent memory | Every handoff is an edge with a timestamp; nothing is forgotten, and every read is "as of time t" |
| Shared state between agents | The learner writes, the router reads; they coordinate only through FalkorDB |
| Handoffs | `HANDED_OFF` edges are the memory, and every routing decision cites them as its path |
| Separate memory per tenant | One FalkorDB graph per repository (`hg:<owner>:<repo>`) |
| Memory that changes behaviour | The same agent routes, keeps, or asks a human depending on what the graph remembers |

## What didn't work, and why that's interesting

**It doesn't beat Microsoft's classifier on a single first guess.** On the issues my agent chooses to route, the two are right equally often (within 0.2 points). I also pre-registered a stricter attempt: at least +2 points of precision while escalating at most 15% of issues. It looked good on development data (+3.8) and failed on the unseen spring period (+0.5). That gap is the classic sign of tuning to noise, and I'd rather show it than hide it.

So I checked the ceiling. Suppose a system knew *exactly* which issues would be handed on, and sent each one to the person's most common recent handoff target. Even that only reaches about 85%, against the bot's 78%. The prize is seven points, and you'd have to know which issue gets forwarded. Knowing who tends to forward isn't enough. I tested every signal I had for that: the issue text (AUC 0.57, close to a coin flip), the person's recent forwarding rate (AUC 0.74, but no override rule that came out ahead), and who filed the issue (no help). The median handoff happens about a day after routing. It depends on workload, leave and conversations that nobody can see when the issue arrives.

**Memory about people goes stale fast.** On development data, the memory's best alternative named the eventual owner of 38% of bounced issues. A month later, on the summer held-out period, it named 13%. Who passes what to whom changes within weeks. To me that's the strongest argument for a graph that keeps learning online over a classifier trained once.

**One thing memory sees that the bot doesn't.** When an engineer forwarded their last three issues in a row, the bot's next pick for them was right only 3 times out of 12. They were usually away. The graph notices that streak; the bot keeps assigning to them. It's rare (under 1% of issues), but it's exactly the kind of judgement that only a memory of past behaviour makes possible.

## Smaller findings (identified after the results, so treat them as descriptive)

- The agent's top three suggestions contain the eventual owner 81% / 69% of the time, against 77% / 62% for the classifier's single pick. That's useful if a human triager picks from suggestions.
- When the agent asks for a human, the classifier's pick really is more likely wrong: 36% / 47% of the time, against 23% / 38% overall. "I'm not sure" turns out to be a useful bounce-risk signal.

## What I learned

- Measure the context layer against the same agent without it. Comparing against a production system made my project look like a loss; comparing against the same AI without memory showed what the graph actually does. Report both.
- Time is the hard part of agent memory. Every leak I found came from the future sneaking in: labels added later, handoffs recorded after routing. Timestamps on edges, plus a `$t` filter in every query, fixed it.
- Let the model judge, and let the graph traverse. Jev is good at one narrow question ("does this issue look like what this person kept?") and weak at multi-hop reasoning and dates. The graph does the hops; code does the dates; the model does one judgement per candidate.

## Try it

- **In the browser:** https://handoff-graph.up.railway.app. Route a real VS Code issue live, explore the handoff memory, or step through the recorded held-out decisions.
- **From Claude Code:** `claude mcp add --transport http handoff-graph https://handoff-graph.up.railway.app/mcp`
- **Reproduce the numbers:** the repo includes the recorded held-out results and the cached decision-model answers. After fetching the public issue data, `--offline` re-runs the replay without an API key.

What I'd do next is change the job, not the model. Instead of competing with the bot on the first guess, the router would step in only after an issue sits untouched with its assignee for a few hours, as a second triager. That's where memory of who actually takes what should matter most.

## AI disclosure

I built this solo with Claude Code as a coding assistant. The design, data model, evaluation protocol and results are mine to explain and defend. Engineers are pseudonymised in this post; the live demo shows public GitHub handles because the routing paths cite public issues.
