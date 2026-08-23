"""Full-content engine mechanics: professions/XP/mastery, recipe gating,
multi-tick station jobs, tool requirements, meteor deadline."""
import copy

import pytest

from reco.engine.content import load_content
from reco.engine.mapgen import init_state
from reco.engine.step import step
from tests.conftest import of_type, rejections
from tests.test_step_core import put


@pytest.fixture
def fcontent(content):
    c = copy.deepcopy(content)
    c["professions"] = {"logging": {}, "mining": {}, "cooking": {}}
    c["mastery_cap"] = 2
    c["xp"] = {"harvest": 5, "craft": 10, "per_level": 100, "max_level": 5}
    c["calories"]["costs"]["study"] = 10
    c["deposits"]["trees"]["profession"] = "logging"
    c["recipes"]["wood_bundle"]["profession"] = "logging"
    c["recipes"]["wood_bundle"]["level"] = 1
    # a multi-tick station recipe
    c["items"]["planks"] = {}
    c["recipes"]["planks"] = {"inputs": {"wood": 2}, "station": "campfire",
                              "ticks": 3, "output_qty": 4,
                              "profession": "logging", "level": 1}
    # a tool and a tool-gated deposit
    c["items"]["stone_axe"] = {"tool": {"kind": "axe", "bonus": 1}}
    c["items"]["iron_ore"] = {}
    c["deposits"]["iron_vein"] = {"yields": "iron_ore", "terrain": "mountain",
                                  "qty_min": 10, "qty_max": 20,
                                  "requires_tool": "pickaxe"}
    return c


@pytest.fixture
def fstate(fcontent):
    return init_state(seed=42, content=fcontent, agent_ids=["a1", "a2", "a3"])


class TestStudyAndMastery:
    def test_study_grants_level_one(self, fstate, fcontent):
        new, events = step(fstate, {"a1": [{"verb": "study", "profession": "logging"}]}, fcontent)
        assert new["agents"]["a1"]["skills"]["logging"] == {"xp": 0, "level": 1}
        assert of_type(events, "studied")

    def test_mastery_cap_enforced(self, fstate, fcontent):
        bundle = [{"verb": "study", "profession": p} for p in ["logging", "mining", "cooking"]]
        new, events = step(fstate, {"a1": bundle}, fcontent)
        assert len(new["agents"]["a1"]["skills"]) == 2
        assert rejections(events, "a1", "R_MASTERY_CAP")

    def test_unknown_profession_rejected(self, fstate, fcontent):
        _, events = step(fstate, {"a1": [{"verb": "study", "profession": "alchemy"}]}, fcontent)
        assert rejections(events, "a1", "R_UNKNOWN_PROFESSION")

    def test_restudy_rejected(self, fstate, fcontent):
        s, _ = step(fstate, {"a1": [{"verb": "study", "profession": "logging"}]}, fcontent)
        _, events = step(s, {"a1": [{"verb": "study", "profession": "logging"}]}, fcontent)
        assert rejections(events, "a1", "R_ALREADY_STUDIED")


class TestXpAndGating:
    def test_harvest_grants_xp_when_studied(self, fstate, fcontent):
        fstate["agents"]["a1"]["skills"] = {"logging": {"xp": 0, "level": 1}}
        fstate["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 9}
        put(fstate, "a1", pos=(3, 3))
        new, _ = step(fstate, {"a1": [{"verb": "harvest"}]}, fcontent)
        assert new["agents"]["a1"]["skills"]["logging"]["xp"] == 5

    def test_no_xp_when_unstudied(self, fstate, fcontent):
        fstate["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 9}
        put(fstate, "a1", pos=(3, 3))
        new, _ = step(fstate, {"a1": [{"verb": "harvest"}]}, fcontent)
        assert "skills" not in new["agents"]["a1"] or not new["agents"]["a1"]["skills"]

    def test_level_up_at_threshold(self, fstate, fcontent):
        fstate["agents"]["a1"]["skills"] = {"logging": {"xp": 95, "level": 1}}
        fstate["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 9}
        put(fstate, "a1", pos=(3, 3))
        new, events = step(fstate, {"a1": [{"verb": "harvest"}]}, fcontent)
        assert new["agents"]["a1"]["skills"]["logging"]["level"] == 2
        assert of_type(events, "level_up")

    def test_gated_recipe_requires_profession(self, fstate, fcontent):
        put(fstate, "a1", inv={"wood": 3})
        _, events = step(fstate, {"a1": [{"verb": "craft", "recipe": "wood_bundle"}]}, fcontent)
        assert rejections(events, "a1", "R_SKILL_TOO_LOW")

    def test_gated_recipe_works_when_studied(self, fstate, fcontent):
        fstate["agents"]["a1"]["skills"] = {"logging": {"xp": 0, "level": 1}}
        put(fstate, "a1", inv={"wood": 3})
        new, _ = step(fstate, {"a1": [{"verb": "craft", "recipe": "wood_bundle"}]}, fcontent)
        assert new["agents"]["a1"]["inventory"] == {"wood_bundle": 1}
        assert new["agents"]["a1"]["skills"]["logging"]["xp"] == 10

    def test_harvest_yield_bonus_at_level_three(self, fstate, fcontent):
        fstate["agents"]["a1"]["skills"] = {"logging": {"xp": 200, "level": 3}}
        fstate["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 9}
        put(fstate, "a1", pos=(3, 3))
        new, _ = step(fstate, {"a1": [{"verb": "harvest"}]}, fcontent)
        assert new["agents"]["a1"]["inventory"] == {"wood": 2}


class TestMultiTickCrafts:
    def setup_job(self, fstate, fcontent):
        fstate["agents"]["a1"]["skills"] = {"logging": {"xp": 0, "level": 1}}
        fstate["tiles"]["3,3"]["building"] = {"kind": "campfire"}
        put(fstate, "a1", pos=(3, 3), inv={"wood": 2})
        return step(fstate, {"a1": [{"verb": "craft", "recipe": "planks"}]}, fcontent)

    def test_start_reserves_inputs_and_occupies_station(self, fstate, fcontent):
        new, events = self.setup_job(fstate, fcontent)
        assert new["agents"]["a1"]["inventory"] == {}
        assert new["tiles"]["3,3"]["job"]["recipe"] == "planks"
        assert of_type(events, "craft_started")

    def test_station_busy_rejects_second_job(self, fstate, fcontent):
        new, _ = self.setup_job(fstate, fcontent)
        new["agents"]["a2"]["skills"] = {"logging": {"xp": 0, "level": 1}}
        put(new, "a2", pos=(3, 3), inv={"wood": 2})
        _, events = step(new, {"a2": [{"verb": "craft", "recipe": "planks"}]}, fcontent)
        assert rejections(events, "a2", "R_STATION_BUSY")

    def test_completes_after_ticks_and_pays_crafter(self, fstate, fcontent):
        s, _ = self.setup_job(fstate, fcontent)
        for _ in range(2):
            s, events = step(s, {}, fcontent)
        assert s["agents"]["a1"]["inventory"] == {"planks": 4}
        assert "job" not in s["tiles"]["3,3"]
        assert of_type(events, "crafted")


class TestTools:
    def test_tool_gated_deposit_requires_tool(self, fstate, fcontent):
        fstate["tiles"]["3,3"]["deposit"] = {"kind": "iron_vein", "item": "iron_ore", "qty": 9}
        put(fstate, "a1", pos=(3, 3))
        _, events = step(fstate, {"a1": [{"verb": "harvest"}]}, fcontent)
        assert rejections(events, "a1", "R_TOOL_REQUIRED")

    def test_tool_bonus_applies(self, fstate, fcontent):
        fstate["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 9}
        put(fstate, "a1", pos=(3, 3), inv={"stone_axe": 1})
        fcontent2 = copy.deepcopy(fcontent)
        fcontent2["deposits"]["trees"]["tool_kind"] = "axe"
        new, _ = step(fstate, {"a1": [{"verb": "harvest"}]}, fcontent2)
        assert new["agents"]["a1"]["inventory"]["wood"] == 2  # 1 + axe bonus


class TestMeteor:
    def test_countdown_resolves_impact(self, fcontent):
        state = init_state(seed=42, content=fcontent, agent_ids=["a1"], meteor_tick=2)
        assert state["meteor"] == {"impact_tick": 2, "outcome": None}
        s, _ = step(state, {}, fcontent)
        s, events = step(s, {}, fcontent)
        assert s["meteor"]["outcome"] == "impact"
        assert of_type(events, "meteor_impact")

    def test_complete_project_defends(self, fcontent):
        state = init_state(seed=42, content=fcontent, agent_ids=["a1"], meteor_tick=1)
        state["project"]["complete"] = True
        s, events = step(state, {}, fcontent)
        assert s["meteor"]["outcome"] == "defended"
        assert of_type(events, "meteor_defended")

    def test_min_contributors_gate(self, fcontent):
        fcontent = copy.deepcopy(fcontent)
        fcontent["project"]["min_contributors"] = 2
        state = init_state(seed=42, content=fcontent, agent_ids=["a1", "a2", "a3"])
        state["project"]["needs"] = {"wood_bundle": 2}
        state["project"]["contributed"] = {"wood_bundle": 1}
        state["project"]["contributed_by"] = {"a1": 1}
        put_agent = state["agents"]["a1"]
        put_agent["pos"] = list(state["project"]["site"])
        put_agent["inventory"] = {"wood_bundle": 1}
        s, events = step(
            state, {"a1": [{"verb": "contribute", "item": "wood_bundle", "qty": 1}]}, fcontent
        )
        # needs met but only one distinct contributor -> not complete
        assert s["project"]["complete"] is False
