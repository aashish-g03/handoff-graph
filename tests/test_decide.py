from handoff_graph.decide import combine, decide, top_margin


class FakeGraph:
    def ro_query(self, *_a, **_k):
        class R:
            result_set = [["some earlier issue"]]
        return R()


class FakeJudge:
    def __init__(self, fit, tie=None, p_handoff=None):
        self._fit, self._tie, self.calls, self.p = fit, tie or {}, [], p_handoff

    def fit(self, issue, profs, contrast=None):
        self.calls.append("fit")
        return {c: self._fit[c] for c in profs}, 100, (self.p if contrast else None)

    def tiebreak(self, issue, profs):
        self.calls.append("tiebreak")
        return {c: self._tie.get(c, 0.0) for c in profs}, 50


ISSUE = {"number": 1, "title": "Tab text hidden", "body": "..."}


def test_combine_is_prior_times_likelihood_normalised():
    post = combine({"a": 0.5, "b": 0.5}, {"a": 0.9, "b": 0.1})
    assert round(post["a"], 2) == 0.9 and round(post["b"], 2) == 0.1


def test_combine_falls_back_to_uniform_when_everything_is_zero():
    assert combine({"a": 0.5, "b": 0.5}, {"a": 0.0, "b": 0.0}) == {"a": 0.5, "b": 0.5}


def test_top_margin():
    ranked, m = top_margin({"a": 0.6, "b": 0.3, "c": 0.1})
    assert ranked[0] == "a" and round(m, 2) == 0.3


def test_clear_winner_routes_with_one_call():
    judge = FakeJudge({"a": 0.9, "b": 0.1})
    d = decide(FakeGraph(), judge, ISSUE, 0, {"a": 0.5, "b": 0.5}, gate=0.2)
    assert d.owner == "a" and judge.calls == ["fit"] and d.jev_calls == 1


def test_close_call_triggers_tiebreak():
    judge = FakeJudge({"a": 0.5, "b": 0.45}, tie={"a": 0.2, "b": 0.8})
    d = decide(FakeGraph(), judge, ISSUE, 0, {"a": 0.5, "b": 0.5}, gate=0.2)
    assert judge.calls == ["fit", "tiebreak"] and d.owner == "b"


def test_still_uncertain_escalates_to_human():
    judge = FakeJudge({"a": 0.5, "b": 0.5}, tie={"a": 0.5, "b": 0.5})
    d = decide(FakeGraph(), judge, ISSUE, 0, {"a": 0.5, "b": 0.5}, gate=0.2)
    assert d.owner is None and "ask a human" in d.reason


def test_graph_prior_shifts_the_decision():
    judge = FakeJudge({"a": 0.6, "b": 0.5})
    d = decide(FakeGraph(), judge, ISSUE, 0, {"a": 0.1, "b": 0.9}, gate=0.2)
    assert d.owner == "b"


def test_handoff_score_moves_mass_from_first_pick_to_alternatives():
    judge = FakeJudge({"a": 0.6, "b": 0.6}, p_handoff=0.9)
    d = decide(FakeGraph(), judge, ISSUE, 0, {"a": 0.7, "b": 0.3}, gate=0.1, first_pick="a")
    assert d.owner == "b"


def test_low_handoff_score_keeps_first_pick():
    judge = FakeJudge({"a": 0.6, "b": 0.6}, p_handoff=0.1)
    d = decide(FakeGraph(), judge, ISSUE, 0, {"a": 0.7, "b": 0.3}, gate=0.1, first_pick="a")
    assert d.owner == "a"
