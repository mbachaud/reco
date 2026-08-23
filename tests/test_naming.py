"""Identity: seeded neutral names for benchmark runs; provider-blocklist
validation for demo-mode self-chosen names."""
from reco.runner.naming import seeded_names, validate_display_name

AGENTS = ["a1", "a2", "a3"]


class TestSeededNames:
    def test_deterministic(self):
        assert seeded_names(42, AGENTS) == seeded_names(42, AGENTS)

    def test_seed_sensitive(self):
        variants = {tuple(seeded_names(n, AGENTS).values()) for n in range(10)}
        assert len(variants) > 1

    def test_unique_names(self):
        names = seeded_names(42, ["a" + str(i) for i in range(20)])
        assert len(set(names.values())) == 20

    def test_all_agents_named(self):
        names = seeded_names(42, AGENTS)
        assert set(names) == set(AGENTS)
        assert all(names.values())


class TestValidation:
    def test_accepts_neutral_name(self):
        assert validate_display_name("Fernwood", set()) is None

    def test_rejects_provider_names(self):
        for bad in ["Claude", "gpt-master", "GeminiFan", "OpenAI-Bot", "sonnet4",
                    "anthropic_agent", "Mr Google", "antigravity1", "OpusPrime"]:
            assert validate_display_name(bad, set()) is not None, bad

    def test_rejects_duplicates_case_insensitive(self):
        assert validate_display_name("Fern", {"fern"}) is not None

    def test_rejects_bad_lengths(self):
        assert validate_display_name("ab", set()) is not None
        assert validate_display_name("x" * 21, set()) is not None

    def test_rejects_weird_characters(self):
        assert validate_display_name("Fern<script>", set()) is not None
