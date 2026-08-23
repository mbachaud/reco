"""Map generation: fully deterministic from seed, zone-based so pilot agents
spawn adjacent to exactly one resource type, Beacon site at center."""
from reco.engine.content import load_content
from reco.engine.hashing import sha256_hex
from reco.engine.mapgen import init_state

AGENTS = ["a1", "a2", "a3"]


def make(seed=42):
    return init_state(seed=seed, content=load_content("slice"), agent_ids=AGENTS)


class TestDeterminism:
    def test_same_seed_identical_state(self):
        assert make(42) == make(42)
        assert sha256_hex(make(42)) == sha256_hex(make(42))

    def test_different_seed_different_state(self):
        assert make(1) != make(2)

    def test_state_is_canonical_hashable(self):
        assert len(sha256_hex(make())) == 64


class TestMapShape:
    def test_dimensions_and_coverage(self):
        s = make()
        assert s["width"] == 12 and s["height"] == 12
        assert len(s["tiles"]) == 144
        assert all(
            t["terrain"] in {"forest", "mountain", "plains", "water"}
            for t in s["tiles"].values()
        )

    def test_deposits_match_zone_terrain(self):
        s = make()
        for tile in s["tiles"].values():
            if tile["deposit"] is not None:
                kind = tile["deposit"]["kind"]
                expected = {"trees": "forest", "stone_outcrop": "mountain", "berry_bush": "plains"}
                assert tile["terrain"] == expected[kind]
                assert tile["deposit"]["qty"] > 0

    def test_beacon_site_at_center(self):
        s = make()
        assert s["project"]["site"] == [6, 6]
        center = s["tiles"]["6,6"]
        assert center["building"] == {"kind": "beacon_site"}
        assert center["deposit"] is None
        assert s["project"]["needs"] == {"wood_bundle": 1, "stone_block": 1, "cooked_meal": 1}
        assert s["project"]["contributed"] == {}
        assert s["project"]["complete"] is False


class TestAgents:
    def test_agents_initialized(self):
        s = make()
        assert set(s["agents"]) == set(AGENTS)
        for a in s["agents"].values():
            assert a["calories"] == 1000
            assert a["inventory"] == {}
            assert a["scratchpad"] == ""

    def test_three_agents_spawn_in_three_distinct_zones(self):
        s = make()
        zones = set()
        for a in s["agents"].values():
            x, y = a["pos"]
            zones.add(s["tiles"][f"{x},{y}"]["terrain"])
        assert zones == {"forest", "mountain", "plains"}

    def test_priority_is_seed_shuffled_permutation(self):
        s = make()
        assert sorted(s["priority"]) == sorted(AGENTS)
        perms = {tuple(init_state(seed=n, content=load_content("slice"), agent_ids=AGENTS)["priority"]) for n in range(12)}
        assert len(perms) > 1
