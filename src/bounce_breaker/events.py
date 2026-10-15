"""Turn raw GitHub issue timelines into clean, timestamped events.

Everything downstream (ingestion, the learner, the replay) works on these
structures, so the "no peeking into the future" rules are enforced here:
an issue's areas are always asked for *as of* a timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# GitHub often records "assign B" a little before "unassign A" in the same handoff (measured: 433 cases within 2 min).
HANDOFF_SLACK_S = 120

BOT_LOGINS = {"vs-code-engineering", "vscodenpa", "github-actions", "copilot-swe-agent"}

# Labels that describe workflow state, not which part of the product an issue is about.
WORKFLOW_LABELS = {
    "bug", "feature-request", "new release", "unreleased", "insiders-released", "info-needed",
    "verified", "triage-needed", "spam", "testplan-item", "stale", "verification-needed",
    "error-telemetry", "ai-generated", "recent-regression", "ai-analyzed", "on-testplan", "polish",
    "ai-translated", "stable-anomaly", "verification-found", "important", "errors-fix", "invalid",
    "debt", "UBB", "regression", "verification-steps-needed", "under-discussion", "upstream",
    "blocked", "endgame-plan", "candidate", "invalid-testplan-item", "flaky-test",
    "author-verification-requested", "papercut :drop_of_blood:", "unit-test-failure",
    "smoke-test-failure", "confirmation-pending", "pr-test-failure-triage", "duplicate",
    "agent-bakeoff", "integration-test-failure", "confirmed", "upstream-issue-linked",
    "engineering", "wont-fix", "upstream-issue-fixed", "test-disabled", "repro-steps-needed",
    "accessibility-sla", "plg", "agent-host-mitigated", "chat-perf-regression",
}


def ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def is_area_label(name: str) -> bool:
    return not (name.startswith(("*", "~")) or name in WORKFLOW_LABELS)


def is_bot(login: str | None) -> bool:
    return bool(login) and (login in BOT_LOGINS or login.endswith("[bot]"))


@dataclass(frozen=True)
class LabelInterval:
    area: str
    added_at: int
    added_by: str | None
    removed_at: int | None = None


@dataclass(frozen=True)
class Assignment:
    login: str
    at: int
    by: str | None
    removed_at: int | None = None
    removed_by: str | None = None


@dataclass(frozen=True)
class Handoff:
    issue: int
    from_login: str
    to_login: str
    at: int
    by: str | None
    kind: str  # "forward" (first assignee passed it on), "claim" (new owner took it), "reassign" (someone else moved it)
    first_pick_by_bot: bool
    areas: tuple[str, ...]


@dataclass
class Issue:
    number: int
    title: str
    created_at: int
    state: str
    author: str | None
    labels: list[LabelInterval] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)

    def areas_at(self, t: int) -> tuple[str, ...]:
        """Area labels present on the issue at time t (added before t, not yet removed)."""
        live = {
            iv.area for iv in self.labels
            if iv.added_at <= t and (iv.removed_at is None or iv.removed_at > t)
        }
        return tuple(sorted(live))

    @property
    def routing_time(self) -> int:
        """When the first routing decision was made: the first assignment, else creation."""
        return self.assignments[0].at if self.assignments else self.created_at

    @property
    def first_pick(self) -> Assignment | None:
        return self.assignments[0] if self.assignments else None


def _login(obj) -> str | None:
    return (obj or {}).get("login")


def parse_issue(raw: dict) -> Issue:
    issue = Issue(
        number=raw["number"],
        title=raw.get("title") or "",
        created_at=ts(raw["createdAt"]),
        state=raw.get("state", ""),
        author=_login(raw.get("author")),
    )
    open_labels: dict[str, LabelInterval] = {}
    open_assign: dict[str, Assignment] = {}
    events = sorted(raw["timelineItems"]["nodes"], key=lambda e: e.get("createdAt") or "")
    for e in events:
        kind, at, by = e["__typename"], ts(e["createdAt"]), _login(e.get("actor"))
        if kind == "LabeledEvent":
            name = e["label"]["name"]
            if is_area_label(name) and name not in open_labels:
                open_labels[name] = LabelInterval(name, at, by)
        elif kind == "UnlabeledEvent":
            name = e["label"]["name"]
            if name in open_labels:
                iv = open_labels.pop(name)
                issue.labels.append(LabelInterval(iv.area, iv.added_at, iv.added_by, at))
        elif kind == "AssignedEvent":
            who = _login(e.get("assignee"))
            if who and who not in open_assign:
                open_assign[who] = Assignment(who, at, by)
        elif kind == "UnassignedEvent":
            who = _login(e.get("assignee"))
            if who in open_assign:
                a = open_assign.pop(who)
                issue.assignments.append(Assignment(a.login, a.at, a.by, at, by))
    issue.labels.extend(open_labels.values())
    issue.assignments.extend(open_assign.values())
    issue.labels.sort(key=lambda iv: iv.added_at)
    issue.assignments.sort(key=lambda a: a.at)
    return issue


def derive_handoffs(issue: Issue) -> list[Handoff]:
    """A handoff is: A was assigned, A got unassigned, and B was assigned at or after A's removal.

    Adding a second assignee while the first stays is collaboration, not a handoff.
    """
    out: list[Handoff] = []
    first = issue.first_pick
    first_by_bot = bool(first and is_bot(first.by))
    for a in issue.assignments:
        if a.removed_at is None:
            continue
        nxt = next(
            (b for b in issue.assignments if b.login != a.login and b.at >= a.removed_at - HANDOFF_SLACK_S),
            None,
        )
        if nxt is None:
            continue
        if nxt.by == a.login:
            kind = "forward"
        elif nxt.by == nxt.login:
            kind = "claim"
        else:
            kind = "reassign"
        out.append(Handoff(
            issue=issue.number, from_login=a.login, to_login=nxt.login, at=nxt.at, by=nxt.by,
            kind=kind, first_pick_by_bot=first_by_bot and a is first,
            areas=issue.areas_at(nxt.at),
        ))
    return out


def final_owners(issue: Issue) -> tuple[str, ...]:
    """People still assigned at the end of the data; the replay's ground truth."""
    return tuple(a.login for a in issue.assignments if a.removed_at is None)
