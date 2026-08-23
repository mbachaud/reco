"""Provisioner: the food-focused scripted role for full-content runs.
Studies foraging + cooking, builds a campfire, cooks meals, gifts them to the
hungriest settlers, and advertises in chat."""
import pytest

from reco.engine.content import load_content
from reco.engine.mapgen import init_state
from reco.engine.step import step
from reco.gateway.drivers.scripted import decide_scripted


@pytest.fixture(scope="module")
def full():
    return load_content("full")


def make(full, n=3):
    ids = [f"a{i}" for i in range(1, n + 1)]
    return init_state(seed=7, content=full, agent_ids=ids, width=24, height=24)


class TestPolicy:
    def test_studies_foraging_then_cooking(self, full):
        state = make(full)
        b1 = decide_scripted(state, "a3", "provisioner", full)
        assert {"verb": "study", "profession": "foraging"} in b1
        state["agents"]["a3"]["skills"] = {"foraging": {"xp": 0, "level": 1}}
        b2 = decide_scripted(state, "a3", "provisioner", full)
        assert {"verb": "study", "profession": "cooking"} in b2

    def test_builds_campfire_when_stocked_and_none_exists(self, full):
        state = make(full)
        a = state["agents"]["a3"]
        a["skills"] = {"foraging": {"xp": 0, "level": 1}, "cooking": {"xp": 0, "level": 1}}
        a["inventory"] = {"wood": 2, "stone": 1}
        pos = a["pos"]
        state["tiles"][f"{pos[0]},{pos[1]}"]["building"] = None
        state["tiles"][f"{pos[0]},{pos[1]}"]["deposit"] = None
        bundle = decide_scripted(state, "a3", "provisioner", full)
        assert {"verb": "build", "building": "campfire"} in bundle

    def test_cooks_on_campfire_with_berries(self, full):
        state = make(full)
        a = state["agents"]["a3"]
        a["skills"] = {"foraging": {"xp": 0, "level": 1}, "cooking": {"xp": 0, "level": 1}}
        a["inventory"] = {"berries": 3}
        pos = a["pos"]
        state["tiles"][f"{pos[0]},{pos[1]}"]["building"] = {"kind": "campfire"}
        bundle = decide_scripted(state, "a3", "provisioner", full)
        assert {"verb": "craft", "recipe": "cooked_meal"} in bundle

    def test_gifts_meal_to_hungriest(self, full):
        state = make(full)
        a = state["agents"]["a3"]
        a["skills"] = {"foraging": {"xp": 0, "level": 1}, "cooking": {"xp": 0, "level": 1}}
        a["inventory"] = {"cooked_meal": 2}
        state["agents"]["a1"]["calories"] = 900
        state["agents"]["a2"]["calories"] = 150  # hungriest
        bundle = decide_scripted(state, "a3", "provisioner", full)
        offers = [x for x in bundle if x["verb"] == "offer"]
        assert offers and offers[0]["to"] == "a2"
        assert offers[0]["give"] == {"cooked_meal": 1} and offers[0]["want"] == {}


class TestSoloKitchen:
    def test_sixty_tick_solo_run_produces_meals(self, full):
        state = make(full, n=2)
        cooked = 0
        for _ in range(60):
            bundles = {
                "a1": decide_scripted(state, "a1", "random", full),
                "a2": decide_scripted(state, "a2", "provisioner", full),
            }
            state, events = step(state, bundles, full)
            cooked += sum(
                1 for e in events
                if e["type"] == "crafted" and e["recipe"] == "cooked_meal"
                and e["agent"] == "a2"
            )
        assert cooked >= 1, "provisioner never cooked a meal in 60 ticks"
