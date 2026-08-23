"""Metrics: real-goods numeraire (immune to currency games), integer-only so
records stay canonical, derived deterministically from content."""
from reco.engine.hashing import canonical_json
from reco.runner.metrics import compute_metrics, gini_milli, value_table


class TestValueTable:
    def test_raw_items_worth_one(self, content):
        values = value_table(content)
        assert values["wood"] == 1 and values["stone"] == 1 and values["berries"] == 1

    def test_crafted_value_exceeds_inputs(self, content):
        values = value_table(content)
        assert values["wood_bundle"] == 4  # 3 wood + 1 labor
        assert values["cooked_meal"] == 4

    def test_deterministic(self, content):
        assert value_table(content) == value_table(content)


class TestGini:
    def test_equal_wealth_is_zero(self):
        assert gini_milli([10, 10, 10]) == 0

    def test_total_inequality_approaches_limit(self):
        # For n=3, max Gini = (n-1)/n = 0.667
        assert gini_milli([0, 0, 30]) == 667

    def test_empty_and_zero_safe(self):
        assert gini_milli([]) == 0
        assert gini_milli([0, 0]) == 0


class TestComputeMetrics:
    def test_integer_only_and_canonical(self, state, content):
        events = [
            {"type": "harvested", "agent": "a1", "item": "wood", "qty": 1, "pos": [3, 3]},
            {"type": "crafted", "agent": "a1", "recipe": "wood_bundle"},
            {"type": "offer_accepted", "offer_id": "o1", "from": "a1", "to": "a2"},
            {"type": "chat", "channel": "global", "from": "a2", "text": "hi"},
            {"type": "rejected", "agent": "a3", "action_index": 0, "verb": "harvest",
             "code": "R_DEPLETED", "reason": "x"},
        ]
        m = compute_metrics(state, events, content)
        canonical_json(m)  # must not raise: ints/strings only
        assert m["production_value"] == 1 + 4  # 1 wood + 1 wood_bundle
        assert m["trade_count"] == 1
        assert m["chat_count"] == 1
        assert m["rejection_count"] == 1
        assert m["calories_mean"] == 1000
        assert "wealth_gini_milli" in m

    def test_trade_volume_values_goods_moved(self, state, content):
        state["offers"]["o1"] = {"from": "a1", "to": "a2", "give": {"wood_bundle": 1},
                                 "want": {"stone": 2}, "expires": 9}
        events = [{"type": "offer_accepted", "offer_id": "o1", "from": "a1", "to": "a2"}]
        m = compute_metrics(state, events, content, closed_offers={"o1": state["offers"]["o1"]})
        assert m["trade_volume"] == 4 + 2
