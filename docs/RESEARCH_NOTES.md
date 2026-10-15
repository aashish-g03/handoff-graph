# Idea C data spike — 2026-10-16

Verdict: PASS. A real multi-hop chain exists where the retracted claim carries through the citing sentences.

## Chain (Semantic Scholar paperIds)
- Hop 0 (RETRACTED 2024): Lesné et al. 2006, "A specific amyloid-β protein assembly in the brain impairs memory" (Nature, DOI 10.1038/nature04533), S2 59ac83c0996f36ac23f94ddad3d96782c9f157a8
  - 2628 citers, 804 with citing sentences, 187 sentences mention Aβ*56 by name
- Hop 1: "Plaque-bearing mice with reduced levels of oligomeric amyloid-beta assemblies have intact memory" (2008), ee8f7027a85eb6188e8d64ad88f28f88f360f1c5
  - intents [background, methodology, result]
  - citing sentence: "The data support previous studies showing the importance of Aβ*56 in memory dysfunction (Lesne et al., 2006)"
- Hop 2: 174 citers, of which **102 do NOT cite the retracted paper directly**, so one-hop tools (Feet of Clay, scite, Zotero) can't see them. Examples that carry the claim:
  - 777bfcce793c09a3eeb7b31d7d84edd5f568024e (2021) "Polymorphic SERPINA3…": "strong association between oligomeric Aβ56 and memory loss in Tg2576 mice was observed [50]"
  - 47237402397448be65cf520e4fc0c79b69fd39fa (2019) "Amyloid Beta and MicroRNAs in AD"
  - 933434614e60ef8debfb537a2f98e537623313f9 (2026) nanoparticle drug-delivery review

## Lessons that shape the design
1. **S2 intents / isInfluential metadata is unreliable.** In the Surgisphere case (DOI 10.1016/S0140-6736(20)31180-6), the meta-analysis aa66f291… is flagged "influential", but its sentence says the study "was subsequently retracted and therefore removed". An LLM judging the citing sentence is essential, not decoration.
2. **Contamination is claim-level, not paper-level.** In the Surgisphere chain, hop 2 (214cce76…) cites hop 1 for its computational-screening method, not the retracted cardiac-risk result, so the chain breaks there. The agent must track WHICH claim is inherited.
3. Many citers cite the retraction *as a subject* (meta-research on retractions), so they are not contaminated. This is a needed verdict class.
4. Unauthenticated S2 rate limit hits 429 often; retry with backoff works but get an API key.
5. Citing-sentence coverage is about 30% (804/2628, 213/738), so "context not available" must be an honest verdict.

Raw data: hop1.json, hop2a.json, hop2b.json, lesne1.json, hop2c.json; script hop.py

# Dev-tools transfer check (Stack Overflow, pandas DataFrame.append, removed in 2.0, Apr 2023)
- 100+ questions link to the canonical Q 10715965 (explicit Q->Q edges via /linked).
- Regex false positives are real: the 817-score answer 17496530 does NOT use df.append (it is a df.loc answer).
- Verified stale answers with no warning: 47979665 (score 467), 31675177 (115, df = df.append in a loop), 42723801 (108, edited Mar 2023, still no warning).
- Across 45 linked questions / 106 answers: 16 use df.append, 15 carry no deprecation/removal warning, 1 was written after the removal.
- Answer->answer hyperlinks that repeat the pattern: 0 found. Propagation runs through Q->Q linked/duplicate edges plus shared API symbols, not explicit citations. The chain story is weaker than the research-paper one; the invalidation join goes Answer-USES->Symbol-REMOVED_IN->Release.

# Triage Router measurement spike (2026-10-16), data in scratchpad/triage/
Data:
- 315 kubernetes/kubernetes issues closed (completed) 2026-04-01..10-01 whose closing PR was merged.
- All 585 OWNERS files plus OWNERS_ALIASES.
- 1682 merged PRs from 2025-10..2026-03 as the activity history, with no overlap with the test window.
Method: non-LLM signal check (scripts fetch_issues.py, fetch_prs.py, evalr.py).
- 125/315 (40%) were fixed by the issue's own author, so routing is trivial for those.
- Ground truth "fix-PR author" (190 issues): graph top-5 15.3% vs random-OWNERS 4.2%. Low in absolute terms: 45% of fixers had never merged before (volunteers) and only 30% are in OWNERS. This is a poor ground truth for routing.
- Ground truth "approver of the fix PR" (120 issues), i.e. who should own/handle it:
  - graph (OWNERS dirs from sig/area labels + paths mentioned in the body; ranked by merge activity; approver x2; emeritus removed): top1 29.2%, top3 35.0%, top5 54.2%
  - random OWNERS pick, i.e. Prow blunderbuss (expected): top1 2.1%, top3 6.3%, top5 10.4%
  - the approver is in the label-derived OWNERS pool 78% of the time
- That's about 14x better than the bot Kubernetes runs today at top-1, before adding any LLM or handoff memory.
TODO:
- LLM graph-off baseline (issue text + repo search).
- DEFERS_TO memory from reassignment comments.
- Note: FalkorDB pageRank has no personalization; use a traversal score.

# Bounce-learning check (2026-10-16)
- Kubernetes (315 issues): 37 had some toss (sig label removed, unassigned, or a /remove-sig command). But 0 toss pairs recur, and person handoffs are mostly volunteers claiming issues, so there's no learnable pattern. Use k8s for ownership only.
- Mozilla Bugzilla, Core product: 600 bugs with a component change Apr–Sep 2026 (query capped at 600). Excluding Untriaged and web-platform-tests (automated syncs):
  - 225 bugs were moved by humans, 274 moves in total.
  - 35 (from -> to) pairs recur 2+ times, 14 recur 3+ times. Top pairs:
    - Graphics -> Graphics: Text (14)
    - Graphics: Text -> Layout: Text and Fonts (7)
    - Graphics -> CanvasWebGL (7)
    - JS Engine -> WebAssembly (5)
  - The no-auth REST API has full history and a triage_owner per component. LEARNABLE.
- Decision: the bounce-learning demo runs on Bugzilla. Kubernetes ownership routing is an optional second dataset.

# Active-project check (2026-10-16), data in scratchpad/active/
Recent issues sampled per repo (600 each):
- next.js 0% reassigned
- pytorch 1%
- rust 1%
- vscode 28% had some label/assignee churn
FULL VS Code pull, issues created 2026-06-01..10-15 (vscode_all.json):
- 11,734 issues, 10,446 assigned.
- 64% of first assignments were made by the triage bot (vs-code-engineering).
- 1,893 reassigned (first assignee removed, someone else assigned) = 18.1% of assigned issues. 72% of those followed a BOT first assignment, i.e. the deployed bot misroutes and humans correct it.
- Recurring handoffs: 322 pairs repeat 2+ times, 175 3+ times, 72 5+ times.
  - benibenj -> mrleemurray 82
  - benibenj -> hawkticehurst 58
  - pwang347 -> aeschli 42
  - sandy081 -> connor4312 39
- Topic-specific (from, to, label):
  - benibenj -> mrleemurray on 'modernization' 61
  - ... on 'ux' 18
  - roblourens -> connor4312 on 'agent-host' 10
  - lramos15 -> vritant24 on 'model-byok' 9
- This is a perfect DEFERS_TO{topic} memory signal on a hyper-active 2026 project (AI agent features).
=> Switch the demo dataset from Mozilla to microsoft/vscode (MIT; public GitHub API).

# Build night 1 findings (2026-10-16)
- Strict handoff definition (A unassigned, then B assigned): 1,602/10,446 assigned issues (15.3%). Kinds: 1,291 forward, 330 reassign, 316 claim.
- **Labels are mostly added AFTER routing.** Only 389/1,937 handoffs had an area label at handoff time. Earlier "61x on modernization" used future labels (leakage). At routing time the topic must come from the issue TEXT, which becomes Jev's job.
- Graph after ingest: 11,734 Issue, 73 Person, 281 Area; 14,190 ASSIGNED, 4,744 HAS_LABEL; 11,663 issues with bodies. Re-ingest leaves counts unchanged (idempotent).
- First end-to-end route, #340427 "ModernUI Tab is surpressing all the Text":
  - The bot picked @benibenj; the real final owners were @mrleemurray and @chryw.
  - With memory: @hawkticehurst and @mrleemurray tie (64 earlier forwards each from @benibenj). The graph narrows to the right pair; the TEXT has to break the tie.
- Next: Jev Choice over the graph candidates, using a per-candidate profile (titles of issues they previously received from the same first pick).
- Local ports: FalkorDB 6380, Browser 3001 (6379 is taken on this machine). The docker compose plugin is broken locally; plain `docker run` is used and docker-compose.yml is kept for submitters.
HOLDOUT command: uv run python -m handoff_graph.replay --arms bot,graph,jev_nograph,jev_keep,jev_graph --holdout  (commit d974fa6, 2026-10-15T20:26:14Z)
