"""Scripted bots: deterministic policies good enough to complete the Beacon
cooperatively (greedy trio) and to fuzz the engine (random walker)."""
from reco.engine.content import load_content
from reco.engine.mapgen import init_state
from reco.engine.step import KNOWN_VERBS, step
from reco.gateway.drivers.scripted import decide_scripted

AGENTS = {"a1": "wood", "a2": "stone", "a3": "meal"}


def make(seed=42):
    content = load_content("slice")
    return content, init_state(seed=seed, content=content, agent_ids=sorted(AGENTS))


class TestPolicies:
    def test_deterministic(self):
        content, state = make()
        b1 = decide_scripted(state, "a1", "wood", content)
        b2 = decide_scripted(state, "a1", "wood", content)
        assert b1 == b2

    def test_wood_bot_harvests_on_deposit(self):
        content, state = make()
        state["agents"]["a1"]["pos"] = [3, 3]
        state["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 30}
        bundle = decide_scripted(state, "a1", "wood", content)
        assert all(a["verb"] == "harvest" for a in bundle) and bundle

    def test_wood_bot_crafts_bundle_when_stocked(self):
        content, state = make()
        state["agents"]["a1"]["inventory"] = {"wood": 5}
        state["tiles"]["3,3"]["deposit"] = None
        state["agents"]["a1"]["pos"] = [3, 3]
        bundle = decide_scripted(state, "a1", "wood", content)
        assert {"verb": "craft", "recipe": "wood_bundle"} in bundle

    def test_meal_bot_asks_for_materials_while_waiting(self):
        content, state = make()
        state["tick"] = 3  # a multiple of the ask cadence
        me = state["agents"]["a3"]
        me["inventory"] = {"berries": 3}
        me["pos"] = [6, 7]  # at the default build tile beside the site
        bundle = decide_scripted(state, "a3", "meal", content)
        says = [a for a in bundle if a["verb"] == "say"]
        assert says and "wood" in says[0]["text"] and "stone" in says[0]["text"]

    def test_random_bot_emits_known_verbs(self):
        content, state = make()
        for tick in range(10):
            state["tick"] = tick
            for a in AGENTS:
                for action in decide_scripted(state, a, "random", content):
                    assert action["verb"] in KNOWN_VERBS


class TestGreedyTrioCompletesBeacon:
    def test_beacon_complete_within_60_ticks(self):
        content, state = make()
        for _ in range(60):
            bundles = {
                a: decide_scripted(state, a, role, content, roles=AGENTS)
                for a, role in AGENTS.items()
            }
            state, _ = step(state, bundles, content)
            if state["project"]["complete"]:
                break
        assert state["project"]["complete"], (
            f"beacon incomplete after 60 ticks: contributed={state['project']['contributed']}"
        )

    def test_random_trio_never_crashes_engine(self):
        content, state = make(seed=7)
        for _ in range(30):
            bundles = {a: decide_scripted(state, a, "random", content) for a in AGENTS}
            state, events = step(state, bundles, content)
        assert state["tick"] == 30
