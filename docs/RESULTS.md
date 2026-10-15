# Results: one-time HOLDOUT run (frozen design, commit d974fa6)

Command: `uv run python -m bounce_breaker.replay --arms bot,graph,jev_nograph,jev_keep,jev_graph --holdout`
File: `results/replay_20261015T203103Z.json`.
- Model: jev-1.14.0.
- HOLDOUT covers issues routed by the VS Code triage bot between 2026-08-25 and 2026-09-15 (n = 1,133). Truth had 30+ days to settle.
- The gate was tuned on TUNE (Jul 6-19) issues whose bot pick handed off: 0.5 for every Jev arm.

| Arm | Top-1 | Escalated | Precision when routed | Truth in candidates | Bounced issues fixed | Net hops | Jev calls/issue | Median latency |
|---|---|---|---|---|---|---|---|---|
| VS Code bot (deployed) | 76.9% | 0% | 76.9% | 77% | 0/259 | 0 | 0 | - |
| Graph only | 76.9% | 0% | 76.9% | 84% | 0/259 | 0 | 0 | 2 ms |
| Jev, no graph | 18.4% | 66% | 55.0% | 82% | 10/259 | -99 | 1.92 | 716 ms |
| Jev keep-check, no graph | 33.2% | 62% | 86.4% | 77% | 0/259 | 0 | 1.00 | 332 ms |
| **Jev + graph** | 74.3% | 4% | 77.2% | 84% | 1/259 | -2 | 0.81 | 357 ms |

On the 259 bounced issues, the graph's top learned alternative was the final owner 33 times (13%), and the final owner was in the graph's top-5 77 times (30%). The bot's first pick was right 0 times on these, by definition.

## Honest reading
- **The graph is what makes AI routing usable.** Jev with graph memory routes 96% of issues at 77% precision. Without the graph, Jev escalates 62-66% of issues; when it does route, precision is 55% (choosing among people) or 86% (only checking "keep it?").
- **Fixing bounces did NOT replicate on HOLDOUT.** DEV suggested a small gain (+1 net hop, 2-4/68). HOLDOUT shows -2 net hops and 1/259. The memory alternative fell from 38% on DEV to 13% on HOLDOUT, so handoff patterns shift over time.
- **Overall, the agent does not beat the deployed bot** (74.3% vs 76.9% top-1). Most issues never bounce, and forwarding is mostly not predictable from issue text (pooled AUC 0.57; higher only for hub triagers).

## Disclosure
- Two earlier designs were inspected on the pre-protocol score period before the DEV/HOLDOUT split was imposed.
- A 200-issue sample touched HOLDOUT dates before the split.
- A bug (Score probabilities keyed by int) was fixed during DEV.
