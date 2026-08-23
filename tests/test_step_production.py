"""Production phase (eat/craft/build/contribute) and the autonomous world step
(calorie decay, offer expiry, project completion)."""
from reco.engine.step import step
from tests.conftest import of_type, rejections
from tests.test_step_core import put


class TestEat:
    def test_eat_restores_calories_and_consumes(self, state, content):
        put(state, "a1", calories=500, inv={"berries": 2})
        new, events = step(state, {"a1": [{"verb": "eat", "item": "berries"}]}, content)
        # +100 food, -10 decay
        assert new["agents"]["a1"]["calories"] == 590
        assert new["agents"]["a1"]["inventory"] == {"berries": 1}
        assert of_type(events, "ate")

    def test_calories_capped_at_max(self, state, content):
        put(state, "a1", calories=1150, inv={"cooked_meal": 1})
        new, _ = step(state, {"a1": [{"verb": "eat", "item": "cooked_meal"}]}, content)
        assert new["agents"]["a1"]["calories"] == 1200 - 10

    def test_eat_non_food_rejected(self, state, content):
        put(state, "a1", inv={"wood": 1})
        _, events = step(state, {"a1": [{"verb": "eat", "item": "wood"}]}, content)
        assert rejections(events, "a1", "R_NOT_FOOD")

    def test_eat_unheld_rejected(self, state, content):
        _, events = step(state, {"a1": [{"verb": "eat", "item": "berries"}]}, content)
        assert rejections(events, "a1", "R_NOT_HELD")


class TestCraft:
    def test_stationless_craft(self, state, content):
        put(state, "a1", inv={"wood": 3})
        new, events = step(state, {"a1": [{"verb": "craft", "recipe": "wood_bundle"}]}, content)
        assert new["agents"]["a1"]["inventory"] == {"wood_bundle": 1}
        assert of_type(events, "crafted")

    def test_missing_inputs_rejected(self, state, content):
        put(state, "a1", inv={"wood": 2})
        _, events = step(state, {"a1": [{"verb": "craft", "recipe": "wood_bundle"}]}, content)
        assert rejections(events, "a1", "R_MISSING_INPUTS")

    def test_station_recipe_requires_station_tile(self, state, content):
        put(state, "a1", pos=(3, 3), inv={"berries": 3})
        _, events = step(state, {"a1": [{"verb": "craft", "recipe": "cooked_meal"}]}, content)
        assert rejections(events, "a1", "R_NO_STATION")

    def test_station_recipe_at_station(self, state, content):
        state["tiles"]["3,3"]["building"] = {"kind": "campfire"}
        put(state, "a1", pos=(3, 3), inv={"berries": 3})
        new, _ = step(state, {"a1": [{"verb": "craft", "recipe": "cooked_meal"}]}, content)
        assert new["agents"]["a1"]["inventory"] == {"cooked_meal": 1}

    def test_unknown_recipe_rejected(self, state, content):
        _, events = step(state, {"a1": [{"verb": "craft", "recipe": "gold_ingot"}]}, content)
        assert rejections(events, "a1", "R_UNKNOWN_RECIPE")


class TestBuild:
    def test_build_consumes_materials(self, state, content):
        state["tiles"]["3,3"]["building"] = None
        put(state, "a1", pos=(3, 3), inv={"wood": 2, "stone": 1})
        new, events = step(state, {"a1": [{"verb": "build", "building": "campfire"}]}, content)
        assert new["tiles"]["3,3"]["building"] == {"kind": "campfire"}
        assert new["agents"]["a1"]["inventory"] == {}
        assert of_type(events, "built")

    def test_occupied_tile_rejected(self, state, content):
        state["tiles"]["3,3"]["building"] = {"kind": "campfire"}
        put(state, "a1", pos=(3, 3), inv={"wood": 2, "stone": 1})
        _, events = step(state, {"a1": [{"verb": "build", "building": "campfire"}]}, content)
        assert rejections(events, "a1", "R_TILE_OCCUPIED")

    def test_missing_materials_rejected(self, state, content):
        state["tiles"]["3,3"]["building"] = None
        put(state, "a1", pos=(3, 3), inv={"wood": 1})
        _, events = step(state, {"a1": [{"verb": "build", "building": "campfire"}]}, content)
        assert rejections(events, "a1", "R_MISSING_MATERIALS")


class TestContribute:
    def test_contribute_at_site(self, state, content):
        put(state, "a1", pos=(6, 6), inv={"wood_bundle": 1})
        new, events = step(
            state, {"a1": [{"verb": "contribute", "item": "wood_bundle", "qty": 1}]}, content
        )
        assert new["project"]["contributed"] == {"wood_bundle": 1}
        assert new["agents"]["a1"]["inventory"] == {}
        (ev,) = of_type(events, "contributed")
        assert ev["agent"] == "a1"

    def test_contribute_away_from_site_rejected(self, state, content):
        put(state, "a1", pos=(3, 3), inv={"wood_bundle": 1})
        _, events = step(
            state, {"a1": [{"verb": "contribute", "item": "wood_bundle", "qty": 1}]}, content
        )
        assert rejections(events, "a1", "R_WRONG_SITE")

    def test_contribute_unneeded_item_rejected(self, state, content):
        put(state, "a1", pos=(6, 6), inv={"wood": 1})
        _, events = step(state, {"a1": [{"verb": "contribute", "item": "wood", "qty": 1}]}, content)
        assert rejections(events, "a1", "R_NOT_NEEDED")

    def test_project_completes_when_all_needs_met(self, state, content):
        state["project"]["contributed"] = {"wood_bundle": 1, "stone_block": 1}
        put(state, "a1", pos=(6, 6), inv={"cooked_meal": 1})
        new, events = step(
            state, {"a1": [{"verb": "contribute", "item": "cooked_meal", "qty": 1}]}, content
        )
        assert new["project"]["complete"] is True
        assert of_type(events, "project_complete")


class TestWorldStep:
    def test_calorie_decay_applies_to_all(self, state, content):
        new, _ = step(state, {}, content)
        assert all(a["calories"] == 990 for a in new["agents"].values())

    def test_calories_floor_at_zero_with_starving_event(self, state, content):
        put(state, "a1", calories=5)
        new, events = step(state, {}, content)
        assert new["agents"]["a1"]["calories"] == 0
        assert any(e["agent"] == "a1" for e in of_type(events, "starving"))

    def test_starving_event_fires_only_on_transition(self, state, content):
        put(state, "a1", calories=0)
        _, events = step(state, {}, content)
        assert not of_type(events, "starving")
