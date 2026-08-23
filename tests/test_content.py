"""Content loader: the slice dataset loads, validates cross-references, and
rejects broken bundles loudly."""
import pytest

from reco.engine.content import ContentError, load_content


class TestSliceLoads:
    def test_slice_bundle_loads(self):
        c = load_content("slice")
        assert c["name"] == "slice-t1"
        assert c["items"]["berries"]["food"] == 100
        assert c["recipes"]["cooked_meal"]["station"] == "campfire"

    def test_content_hash_is_stable(self):
        assert load_content("slice")["content_hash"] == load_content("slice")["content_hash"]
        assert len(load_content("slice")["content_hash"]) == 64


class TestValidation:
    def test_recipe_with_unknown_input_rejected(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            """
schema_version: 1
name: bad
calories: {start: 1, max: 1, decay_per_tick: 0, costs: {move_per_tile: 0, harvest: 0, craft: 0, build: 0}}
items:
  wood: {}
deposits: {}
recipes:
  plank: {inputs: {unobtainium: 1}, station: null, ticks: 1, output_qty: 1}
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
        with pytest.raises(ContentError, match="unobtainium"):
            load_content(bad)

    def test_recipe_with_unknown_station_rejected(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            """
schema_version: 1
name: bad
calories: {start: 1, max: 1, decay_per_tick: 0, costs: {move_per_tile: 0, harvest: 0, craft: 0, build: 0}}
items:
  wood: {}
  plank: {}
deposits: {}
recipes:
  plank: {inputs: {wood: 1}, station: forge, ticks: 1, output_qty: 1}
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
        with pytest.raises(ContentError, match="forge"):
            load_content(bad)

    def test_deposit_yielding_unknown_item_rejected(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            """
schema_version: 1
name: bad
calories: {start: 1, max: 1, decay_per_tick: 0, costs: {move_per_tile: 0, harvest: 0, craft: 0, build: 0}}
items: {}
deposits:
  trees: {yields: wood, terrain: forest, qty_min: 1, qty_max: 2}
recipes: {}
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
        with pytest.raises(ContentError, match="wood"):
            load_content(bad)
