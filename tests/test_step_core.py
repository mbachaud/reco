"""Step pipeline: purity, determinism, admin/chat/economy/movement/gather
phases, engine-authoritative rejections, and rotating-priority conflicts."""
import copy

from reco.engine.step import step
from tests.conftest import of_type, rejections


def put(state, agent, pos=None, calories=None, inv=None):
    a = state["agents"][agent]
    if pos is not None:
        a["pos"] = list(pos)
    if calories is not None:
        a["calories"] = calories
    if inv is not None:
        a["inventory"] = dict(inv)


class TestPipeline:
    def test_step_is_pure(self, state, content):
        before = copy.deepcopy(state)
        step(state, {"a1": [{"verb": "say", "text": "hi"}]}, content)
        assert state == before

    def test_step_is_deterministic(self, state, content):
        bundles = {"a1": [{"verb": "move", "path": [[3, 4]]}], "a2": [{"verb": "say", "text": "yo"}]}
        assert step(state, bundles, content) == step(state, bundles, content)

    def test_tick_increments(self, state, content):
        new, _ = step(state, {}, content)
        assert new["tick"] == state["tick"] + 1

    def test_unknown_verb_rejected(self, state, content):
        _, events = step(state, {"a1": [{"verb": "teleport"}]}, content)
        assert rejections(events, "a1", "R_UNKNOWN_VERB")

    def test_actions_beyond_cap_rejected(self, state, content):
        bundle = [{"verb": "remember", "text": f"n{i}"} for i in range(10)]
        new, events = step(state, {"a1": bundle}, content)
        assert len(rejections(events, "a1", "R_ACTION_CAP")) == 2
        assert new["agents"]["a1"]["scratchpad"] == "n7"  # first 8 executed


class TestAdminAndChat:
    def test_remember_rewrites_scratchpad(self, state, content):
        new, _ = step(state, {"a1": [{"verb": "remember", "text": "meet a2 at beacon"}]}, content)
        assert new["agents"]["a1"]["scratchpad"] == "meet a2 at beacon"

    def test_remember_too_long_rejected(self, state, content):
        new, events = step(state, {"a1": [{"verb": "remember", "text": "x" * 501}]}, content)
        assert rejections(events, "a1", "R_TOO_LONG")
        assert new["agents"]["a1"]["scratchpad"] == ""

    def test_lookup_returns_private_result(self, state, content):
        _, events = step(state, {"a1": [{"verb": "lookup", "topic": "cooked_meal"}]}, content)
        (result,) = of_type(events, "lookup_result")
        assert result["agent"] == "a1"
        assert "berries" in result["text"]  # recipe inputs are described

    def test_lookup_unknown_topic(self, state, content):
        _, events = step(state, {"a1": [{"verb": "lookup", "topic": "nonsense"}]}, content)
        assert rejections(events, "a1", "R_UNKNOWN_TOPIC")

    def test_lookup_cap(self, state, content):
        bundle = [{"verb": "lookup", "topic": t} for t in ["wood", "stone", "berries"]]
        _, events = step(state, {"a1": bundle}, content)
        assert len(of_type(events, "lookup_result")) == 2
        assert rejections(events, "a1", "R_LOOKUP_CAP")

    def test_say_emits_global_chat(self, state, content):
        _, events = step(state, {"a1": [{"verb": "say", "text": "hello world"}]}, content)
        (msg,) = of_type(events, "chat")
        assert msg["channel"] == "global" and msg["from"] == "a1" and msg["text"] == "hello world"

    def test_say_cap_is_one(self, state, content):
        bundle = [{"verb": "say", "text": "one"}, {"verb": "say", "text": "two"}]
        _, events = step(state, {"a1": bundle}, content)
        assert len(of_type(events, "chat")) == 1
        assert rejections(events, "a1", "R_CHAT_CAP")

    def test_dm_addressed_and_capped(self, state, content):
        bundle = [
            {"verb": "dm", "to": "a2", "text": "one"},
            {"verb": "dm", "to": "a2", "text": "two"},
            {"verb": "dm", "to": "a3", "text": "three"},
        ]
        _, events = step(state, {"a1": bundle}, content)
        dms = [e for e in of_type(events, "chat") if e["channel"] == "dm"]
        assert len(dms) == 2 and all(d["to"] in {"a2", "a3"} for d in dms)
        assert rejections(events, "a1", "R_CHAT_CAP")

    def test_dm_unknown_agent(self, state, content):
        _, events = step(state, {"a1": [{"verb": "dm", "to": "ghost", "text": "hi"}]}, content)
        assert rejections(events, "a1", "R_UNKNOWN_AGENT")

    def test_chat_too_long(self, state, content):
        _, events = step(state, {"a1": [{"verb": "say", "text": "y" * 241}]}, content)
        assert rejections(events, "a1", "R_TOO_LONG")


class TestMovement:
    def test_move_along_path_costs_calories(self, state, content):
        put(state, "a1", pos=(3, 3), calories=1000)
        new, events = step(state, {"a1": [{"verb": "move", "path": [[3, 4], [3, 5]]}]}, content)
        assert new["agents"]["a1"]["pos"] == [3, 5]
        # 2 tiles x 5 cal, then 10 world-step decay
        assert new["agents"]["a1"]["calories"] == 1000 - 10 - 10
        assert of_type(events, "moved")

    def test_move_onto_water_rejected_atomically(self, state, content):
        state["tiles"]["3,4"] = {"terrain": "water", "deposit": None, "building": None}
        put(state, "a1", pos=(3, 3))
        new, events = step(state, {"a1": [{"verb": "move", "path": [[3, 4], [3, 5]]}]}, content)
        assert rejections(events, "a1", "R_IMPASSABLE")
        assert new["agents"]["a1"]["pos"] == [3, 3]

    def test_move_beyond_budget_rejected(self, state, content):
        put(state, "a1", pos=(3, 3))
        path = [[3, 4], [3, 5], [3, 6], [3, 7]]  # 4 > move_points 3
        _, events = step(state, {"a1": [{"verb": "move", "path": path}]}, content)
        assert rejections(events, "a1", "R_MOVE_BUDGET")

    def test_nonadjacent_step_rejected(self, state, content):
        put(state, "a1", pos=(3, 3))
        _, events = step(state, {"a1": [{"verb": "move", "path": [[5, 3]]}]}, content)
        assert rejections(events, "a1", "R_IMPASSABLE")

    def test_starving_agent_limited_to_one_tile(self, state, content):
        put(state, "a1", pos=(3, 3), calories=0)
        new, events = step(state, {"a1": [{"verb": "move", "path": [[3, 4], [3, 5]]}]}, content)
        assert rejections(events, "a1", "R_STARVING")
        new, _ = step(state, {"a1": [{"verb": "move", "path": [[3, 4]]}]}, content)
        assert new["agents"]["a1"]["pos"] == [3, 4]


class TestHarvest:
    def test_harvest_yields_item_and_depletes(self, state, content):
        state["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 5}
        put(state, "a1", pos=(3, 3), calories=1000)
        new, events = step(state, {"a1": [{"verb": "harvest"}]}, content)
        assert new["agents"]["a1"]["inventory"] == {"wood": 1}
        assert new["tiles"]["3,3"]["deposit"]["qty"] == 4
        assert of_type(events, "harvested")

    def test_exhausted_deposit_removed(self, state, content):
        state["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 1}
        put(state, "a1", pos=(3, 3))
        new, _ = step(state, {"a1": [{"verb": "harvest"}]}, content)
        assert new["tiles"]["3,3"]["deposit"] is None

    def test_no_deposit_rejected(self, state, content):
        state["tiles"]["3,3"]["deposit"] = None
        put(state, "a1", pos=(3, 3))
        _, events = step(state, {"a1": [{"verb": "harvest"}]}, content)
        assert rejections(events, "a1", "R_DEPLETED")

    def test_contested_last_unit_goes_to_rotation_winner(self, state, content):
        state["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 1}
        put(state, "a1", pos=(3, 3))
        put(state, "a2", pos=(3, 3))
        bundles = {"a1": [{"verb": "harvest"}], "a2": [{"verb": "harvest"}]}
        new, events = step(state, bundles, content)

        order = state["priority"]  # tick 0 -> rotation offset 0
        winner = min(["a1", "a2"], key=order.index)
        loser = "a2" if winner == "a1" else "a1"
        assert new["agents"][winner]["inventory"] == {"wood": 1}
        assert new["agents"][loser]["inventory"] == {}
        assert rejections(events, loser, "R_DEPLETED")

    def test_starving_agent_can_harvest_food_deposit(self, state, content):
        # A settlement where everyone hits 0 calories must not deadlock while
        # food is still in the ground: harvest stays open for food deposits.
        state["tiles"]["3,3"]["deposit"] = {"kind": "berry_bush", "item": "berries", "qty": 5}
        put(state, "a1", pos=(3, 3), calories=0)
        new, events = step(state, {"a1": [{"verb": "harvest"}]}, content)
        assert not rejections(events, "a1", "R_STARVING")
        assert of_type(events, "harvested")
        assert new["agents"]["a1"]["inventory"] == {"berries": 1}

    def test_starving_agent_cannot_harvest_nonfood_deposit(self, state, content):
        # Starving stays incapacitating for ordinary work: only deposits whose
        # yield item has a food value are exempt, not wood or stone.
        state["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 5}
        put(state, "a1", pos=(3, 3), calories=0)
        new, events = step(state, {"a1": [{"verb": "harvest"}]}, content)
        assert rejections(events, "a1", "R_STARVING")
        assert new["agents"]["a1"]["inventory"] == {}

    def test_rotation_shifts_with_tick(self, state, content):
        # Same contest one tick later must favor the next agent in rotation.
        state["tick"] = 1
        state["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 1}
        put(state, "a1", pos=(3, 3))
        put(state, "a2", pos=(3, 3))
        order = state["priority"]
        rotated = order[1:] + order[:1]
        winner = min(["a1", "a2"], key=rotated.index)
        bundles = {"a1": [{"verb": "harvest"}], "a2": [{"verb": "harvest"}]}
        new, _ = step(state, bundles, content)
        assert new["agents"][winner]["inventory"] == {"wood": 1}


class TestOffers:
    def test_offer_escrows_goods(self, state, content):
        put(state, "a1", inv={"wood": 3})
        bundle = [{"verb": "offer", "to": "a2", "give": {"wood": 2}, "want": {"stone": 1}}]
        new, events = step(state, {"a1": bundle}, content)
        assert new["agents"]["a1"]["inventory"] == {"wood": 1}
        (offer,) = new["offers"].values()
        assert offer["from"] == "a1" and offer["to"] == "a2"
        assert offer["give"] == {"wood": 2} and offer["want"] == {"stone": 1}
        assert of_type(events, "offer_created")

    def test_offer_without_goods_rejected(self, state, content):
        bundle = [{"verb": "offer", "to": "a2", "give": {"wood": 2}, "want": {"stone": 1}}]
        _, events = step(state, {"a1": bundle}, content)
        assert rejections(events, "a1", "R_INSUFFICIENT_GOODS")

    def test_accept_swaps_atomically(self, state, content):
        put(state, "a1", inv={"wood": 2})
        put(state, "a2", inv={"stone": 1})
        mid, _ = step(
            state,
            {"a1": [{"verb": "offer", "to": "a2", "give": {"wood": 2}, "want": {"stone": 1}}]},
            content,
        )
        offer_id = next(iter(mid["offers"]))
        new, events = step(mid, {"a2": [{"verb": "accept", "offer_id": offer_id}]}, content)
        assert new["agents"]["a2"]["inventory"] == {"wood": 2}
        assert new["agents"]["a1"]["inventory"] == {"stone": 1}
        assert new["offers"] == {}
        assert of_type(events, "offer_accepted")

    def test_accept_without_funds_rejected(self, state, content):
        put(state, "a1", inv={"wood": 2})
        mid, _ = step(
            state,
            {"a1": [{"verb": "offer", "to": "a2", "give": {"wood": 2}, "want": {"stone": 1}}]},
            content,
        )
        offer_id = next(iter(mid["offers"]))
        new, events = step(mid, {"a2": [{"verb": "accept", "offer_id": offer_id}]}, content)
        assert rejections(events, "a2", "R_INSUFFICIENT_FUNDS")
        assert offer_id in new["offers"]

    def test_accept_missing_offer_rejected(self, state, content):
        _, events = step(state, {"a2": [{"verb": "accept", "offer_id": "o99"}]}, content)
        assert rejections(events, "a2", "R_OFFER_EXPIRED")

    def test_offer_expires_and_returns_escrow(self, state, content):
        put(state, "a1", inv={"wood": 2})
        s, _ = step(
            state,
            {"a1": [{"verb": "offer", "to": "a2", "give": {"wood": 2}, "want": {"stone": 1}}]},
            content,
        )
        expired_events = []
        for _ in range(content["offers"]["ttl_ticks"] + 1):
            s, events = step(s, {}, content)
            expired_events += of_type(events, "offer_expired")
        assert expired_events
        assert s["offers"] == {}
        assert s["agents"]["a1"]["inventory"] == {"wood": 2}

    def test_starving_agent_can_accept_gift_and_eat_same_tick(self, state, content):
        # Accept is the rescue path for a starving agent: the escrow is already
        # funded by the offerer, and economy runs before production, so one
        # bundle can accept a food gift and eat it in the same tick.
        put(state, "a1", inv={"berries": 2})
        mid, _ = step(
            state,
            {"a1": [{"verb": "offer", "to": "a2", "give": {"berries": 2}, "want": {}}]},
            content,
        )
        offer_id = next(iter(mid["offers"]))
        put(mid, "a2", calories=0)
        bundle = [{"verb": "accept", "offer_id": offer_id}, {"verb": "eat", "item": "berries"}]
        new, events = step(mid, {"a2": bundle}, content)
        assert not rejections(events, "a2", "R_STARVING")
        assert of_type(events, "offer_accepted")
        assert of_type(events, "ate")
        # ate 100-calorie berries, then world-step decay of 10
        assert new["agents"]["a2"]["calories"] == 100 - 10
        assert new["agents"]["a2"]["inventory"] == {"berries": 1}

    def test_open_offer_cap(self, state, content):
        put(state, "a1", inv={"wood": 10})
        bundle = [
            {"verb": "offer", "to": "a2", "give": {"wood": 1}, "want": {"stone": 1}}
            for _ in range(4)
        ]
        new, events = step(state, {"a1": bundle}, content)
        assert len(new["offers"]) == 3
        assert rejections(events, "a1", "R_OFFER_CAP")
