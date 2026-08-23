"""Keyed-hash RNG: every random draw is a pure function of (seed, *key_parts).

No shared consumed stream — unrelated code changes must never reorder anyone
else's draws.
"""
import pytest

from reco.engine.rng import derive, permutation, rand_below


class TestDerive:
    def test_deterministic(self):
        assert derive(42, 3, "harvest", "tile:4,5") == derive(42, 3, "harvest", "tile:4,5")

    def test_different_purpose_different_value(self):
        assert derive(42, 3, "harvest") != derive(42, 3, "conflict")

    def test_different_seed_different_value(self):
        assert derive(1, 3, "harvest") != derive(2, 3, "harvest")

    def test_part_boundaries_matter(self):
        # ("ab", "c") must not collide with ("a", "bc")
        assert derive(0, "ab", "c") != derive(0, "a", "bc")


class TestRandBelow:
    def test_within_range(self):
        for i in range(50):
            assert 0 <= rand_below(7, 10, "test", i) < 10

    def test_deterministic(self):
        assert rand_below(7, 1000, "x") == rand_below(7, 1000, "x")

    def test_not_constant(self):
        values = {rand_below(7, 100, "spread", i) for i in range(50)}
        assert len(values) > 10

    def test_n_one_returns_zero(self):
        assert rand_below(7, 1, "x") == 0

    def test_rejects_nonpositive_n(self):
        with pytest.raises(ValueError):
            rand_below(7, 0, "x")


class TestPermutation:
    def test_is_permutation(self):
        assert sorted(permutation(9, 20, "priority")) == list(range(20))

    def test_deterministic(self):
        assert permutation(9, 20, "priority") == permutation(9, 20, "priority")

    def test_seed_sensitive(self):
        assert permutation(1, 20, "priority") != permutation(2, 20, "priority")

    def test_key_sensitive(self):
        assert permutation(9, 20, "priority") != permutation(9, 20, "spawn")

    def test_empty(self):
        assert permutation(9, 0, "priority") == []
