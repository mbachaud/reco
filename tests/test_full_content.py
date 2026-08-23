"""The full 4-tier dataset: loads clean, professions validate, the Defense
Array is arithmetically infeasible solo (mastery gate) yet feasible for a
coordinated group, observations stay budgeted, and random-bot fuzz replays."""
import pytest

from reco.engine.content import ContentError, load_content
from reco.engine.mapgen import init_state
from reco.gateway.prompts import render_observation, render_static
from reco.runner.metrics import value_table
from reco.runner.orchestrator import run
from reco.runner.replay import replay


@pytest.fixture(scope="module")
def full():
    return load_content("full")


class TestLoads:
    def test_loads_and_hashes(self, full):
        assert full["name"] == "full-t4"
        assert len(full["items"]) >= 35
        assert len(full["professions"]) == 10

    def test_profession_refs_validated(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            """
schema_version: 1
name: bad
calories: {start: 1, max: 1, decay_per_tick: 0, costs: {move_per_tile: 0, harvest: 0, craft: 0, build: 0}}
professions: {logging: {}}
items: {wood: {}, plank: {}}
deposits: {}
recipes:
  plank: {inputs: {wood: 1}, station: null, ticks: 1, output_qty: 1, profession: alchemy, level: 1}
buildings: {}
project: {kind: beacon, needs: {}}
offers: {ttl_ticks: 5, max_open_per_agent: 3}
chat: {max_say_per_tick: 1, max_dm_per_tick: 2, max_chars: 240}
scratchpad_max_chars: 500
lookup_max_per_tick: 2
harvest_yield: 1
move_points: 3
""",
            encoding="utf-8",
        )
        with pytest.raises(ContentError, match="alchemy"):
            load_content(bad)


def crafting_closure_professions(content, item, seen=None):
    """All professions needed to produce an item from raw materials."""
    seen = seen if seen is not None else set()
    recipe = content["recipes"].get(item)
    if recipe is None:
        return seen
    if recipe.get("profession"):
        seen.add(recipe["profession"])
    for sub in recipe["inputs"]:
        crafting_closure_professions(content, sub, seen)
    return seen


class TestBalance:
    def test_project_needs_span_many_professions(self, full):
        professions = set()
        for item in full["project"]["needs"]:
            professions |= crafting_closure_professions(full, item)
        # Mastery cap is 2 -> no single agent can produce the closure.
        assert len(professions) > full["mastery_cap"] * 2
        assert len(professions) >= 5

    def test_project_value_in_feasibility_band(self, full):
        values = value_table(full)
        total = sum(values[item] * qty for item, qty in full["project"]["needs"].items())
        # Rough labor-unit band: too low = trivial, too high = unwinnable
        # for 8-10 agents in a 150-200 tick standard run.
        assert 100 <= total <= 900, total

    def test_min_contributors_set(self, full):
        assert full["project"]["min_contributors"] >= 3


class TestObservationBudget:
    def test_recipes_filtered_by_own_professions(self, full):
        state = init_state(seed=1, content=full, agent_ids=["a1", "a2"])
        state["agents"]["a1"]["skills"] = {"logging": {"xp": 0, "level": 1},
                                           "carpentry": {"xp": 0, "level": 1}}
        names = {"a1": "Ash", "a2": "Brook"}
        text = render_observation(state, "a1", [], names, full)
        assert "- planks:" in text            # own profession (carpentry)
        assert "- wood_bundle:" in text       # ungated
        assert "- defense_frame:" not in text  # industry recipe, not studied
        assert len(text) < 4500

    def test_static_context_mentions_new_systems(self, full):
        text = render_static(full, "Ash")
        for token in ["study", "claim", "create_currency", "mint", "buy", "METEOR", "PROFESSIONS"]:
            assert token in text, token
        assert len(text) < 8000


class TestMapgenVariety:
    def test_all_deposit_kinds_appear_on_a_standard_map(self, full):
        state = init_state(seed=3, content=full, agent_ids=["a1"], width=24, height=24)
        kinds = {t["deposit"]["kind"] for t in state["tiles"].values()
                 if t["deposit"] is not None}
        assert kinds == set(full["deposits"])

    def test_map_size_from_config_flows_to_run(self, tmp_path):
        from reco.runner.orchestrator import run
        from reco.runner.replay import replay

        config = {
            "seed": 11, "ticks": 3, "content": "full",
            "map": {"width": 24, "height": 24},
            "agents": [{"id": "a1", "role": "random"}],
        }
        run(config, tmp_path / "r1")
        replay(tmp_path / "r1")
        from reco.runner.frames import export_frames
        assert export_frames(tmp_path / "r1")["meta"]["width"] == 24


class TestFuzz:
    def test_random_bots_on_full_content_replay_clean(self, tmp_path):
        config = {
            "seed": 11,
            "ticks": 25,
            "content": "full",
            "agents": [{"id": f"a{i}", "role": "random"} for i in range(1, 5)],
        }
        summary = run(config, tmp_path / "rf")
        assert summary["ticks_committed"] == 25
        replay(tmp_path / "rf")
