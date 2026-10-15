from bounce_breaker.events import parse_issue, derive_handoffs, final_owners, is_area_label


def _issue(events, labels=(), number=1, created="2026-07-01T00:00:00Z"):
    return {
        "number": number,
        "title": "t",
        "createdAt": created,
        "state": "OPEN",
        "author": {"login": "reporter"},
        "labels": {"nodes": [{"name": n} for n in labels]},
        "timelineItems": {"nodes": events},
    }


def _assign(who, by, at):
    return {"__typename": "AssignedEvent", "createdAt": at, "actor": {"login": by}, "assignee": {"login": who}}


def _unassign(who, by, at):
    return {"__typename": "UnassignedEvent", "createdAt": at, "actor": {"login": by}, "assignee": {"login": who}}


def _label(name, by, at, removed=False):
    t = "UnlabeledEvent" if removed else "LabeledEvent"
    return {"__typename": t, "createdAt": at, "actor": {"login": by}, "label": {"name": name}}


def test_forward_by_first_assignee_is_a_handoff():
    issue = parse_issue(_issue([
        _assign("alice", "vs-code-engineering", "2026-07-01T01:00:00Z"),
        _unassign("alice", "alice", "2026-07-01T02:00:00Z"),
        _assign("bob", "alice", "2026-07-01T02:00:01Z"),
    ]))
    hs = derive_handoffs(issue)
    assert len(hs) == 1
    h = hs[0]
    assert (h.from_login, h.to_login, h.kind) == ("alice", "bob", "forward")
    assert h.first_pick_by_bot is True


def test_self_claim_is_labelled_claim_not_forward():
    issue = parse_issue(_issue([
        _assign("alice", "vs-code-engineering", "2026-07-01T01:00:00Z"),
        _unassign("alice", "bob", "2026-07-01T02:00:00Z"),
        _assign("bob", "bob", "2026-07-01T02:00:01Z"),
    ]))
    [h] = derive_handoffs(issue)
    assert h.kind == "claim"


def test_adding_a_second_assignee_without_removing_first_is_not_a_handoff():
    issue = parse_issue(_issue([
        _assign("alice", "vs-code-engineering", "2026-07-01T01:00:00Z"),
        _assign("bob", "alice", "2026-07-01T02:00:00Z"),
    ]))
    assert derive_handoffs(issue) == []


def test_handoff_topic_uses_area_labels_present_at_handoff_time_only():
    issue = parse_issue(_issue([
        _label("terminal", "triager", "2026-07-01T00:30:00Z"),
        _label("bug", "triager", "2026-07-01T00:30:00Z"),
        _assign("alice", "vs-code-engineering", "2026-07-01T01:00:00Z"),
        _unassign("alice", "alice", "2026-07-01T02:00:00Z"),
        _assign("bob", "alice", "2026-07-01T02:00:01Z"),
        _label("chat", "bob", "2026-07-02T00:00:00Z"),  # added later: must not leak into the topic
    ]))
    [h] = derive_handoffs(issue)
    assert h.areas == ("terminal",)


def test_labels_at_respects_removal():
    issue = parse_issue(_issue([
        _label("terminal", "x", "2026-07-01T00:00:00Z"),
        _label("terminal", "x", "2026-07-01T05:00:00Z", removed=True),
        _label("chat", "x", "2026-07-01T06:00:00Z"),
    ]))
    from bounce_breaker.events import ts
    assert issue.areas_at(ts("2026-07-01T01:00:00Z")) == ("terminal",)
    assert issue.areas_at(ts("2026-07-01T07:00:00Z")) == ("chat",)


def test_final_owner_is_last_assignee_still_assigned():
    issue = parse_issue(_issue([
        _assign("alice", "vs-code-engineering", "2026-07-01T01:00:00Z"),
        _unassign("alice", "alice", "2026-07-01T02:00:00Z"),
        _assign("bob", "alice", "2026-07-01T02:00:01Z"),
    ]))
    assert final_owners(issue) == ("bob",)


def test_workflow_labels_are_not_areas():
    assert not is_area_label("bug")
    assert not is_area_label("insiders-released")
    assert not is_area_label("*duplicate")
    assert is_area_label("terminal")
    assert is_area_label("agent-host")


def test_assign_b_shortly_before_unassign_a_is_still_a_handoff():
    issue = parse_issue(_issue([
        _assign("alice", "vs-code-engineering", "2026-07-01T01:00:00Z"),
        _assign("bob", "alice", "2026-07-01T02:00:00Z"),
        _unassign("alice", "alice", "2026-07-01T02:00:40Z"),
    ]))
    [h] = derive_handoffs(issue)
    assert (h.from_login, h.to_login, h.kind) == ("alice", "bob", "forward")
