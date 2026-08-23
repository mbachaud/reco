"""Prompt rendering: byte-stable static context, compact fixed-order text
observations with map, chat privacy, and error echo."""
from reco.gateway.prompts import render_observation, render_static

NAMES = {"a1": "Ash", "a2": "Brook", "a3": "Cedar"}


class TestStatic:
    def test_contains_rules_and_grammar(self, content):
        text = render_static(content, "Ash")
        for token in ["move", "harvest", "craft", "offer", "contribute", "JSON"]:
            assert token in text
        assert "Ash" in text

    def test_byte_identical_per_agent(self, content):
        assert render_static(content, "Ash") == render_static(content, "Ash")

    def test_stays_in_budget(self, content):
        assert len(render_static(content, "Ash")) < 6000  # ~1.5k tokens


class TestObservation:
    def test_self_state_rendered(self, state, content):
        state["agents"]["a1"]["inventory"] = {"wood": 4}
        state["agents"]["a1"]["calories"] = 850
        text = render_observation(state, "a1", [], NAMES, content)
        assert "850" in text and "wood x4" in text
        assert "Ash" in text

    def test_map_is_seven_rows_with_you_centered(self, state, content):
        text = render_observation(state, "a1", [], NAMES, content)
        map_lines = [l for l in text.splitlines() if l.startswith("|")]
        assert len(map_lines) == 7
        assert map_lines[3][4] == "@"  # center of "|" + 7 chars

    def test_other_agents_marked(self, state, content):
        state["agents"]["a2"]["pos"] = list(state["agents"]["a1"]["pos"])
        state["agents"]["a2"]["pos"][0] += 1
        text = render_observation(state, "a2", [], NAMES, content)
        assert "*" in "".join(l for l in text.splitlines() if l.startswith("|"))

    def test_chat_digest_respects_privacy(self, state, content):
        events = [
            {"type": "chat", "channel": "global", "from": "a2", "text": "hello all"},
            {"type": "chat", "channel": "dm", "from": "a2", "to": "a1", "text": "psst a1"},
            {"type": "chat", "channel": "dm", "from": "a2", "to": "a3", "text": "secret for a3"},
        ]
        text = render_observation(state, "a1", events, NAMES, content)
        assert "hello all" in text and "Brook" in text
        assert "psst a1" in text
        assert "secret for a3" not in text

    def test_rejection_feedback_echoed(self, state, content):
        events = [
            {"type": "rejected", "agent": "a1", "action_index": 0, "verb": "harvest",
             "code": "R_DEPLETED", "reason": "no harvestable deposit on this tile"},
            {"type": "rejected", "agent": "a2", "action_index": 0, "verb": "craft",
             "code": "R_NO_STATION", "reason": "requires a campfire"},
        ]
        text = render_observation(state, "a1", events, NAMES, content)
        assert "R_DEPLETED" in text
        assert "R_NO_STATION" not in text  # other agents' rejections are private

    def test_parse_errors_echoed(self, state, content):
        text = render_observation(
            state, "a1", [], NAMES, content,
            parse_errors=[{"code": "PE_SCHEMA", "reason": "move: arg 'path' has wrong type"}],
        )
        assert "PE_SCHEMA" in text

    def test_offers_visible_to_parties_only(self, state, content):
        state["offers"]["o1"] = {"from": "a2", "to": "a1", "give": {"wood": 2},
                                 "want": {}, "expires": 9}
        text1 = render_observation(state, "a1", [], NAMES, content)
        assert "o1" in text1 and "wood" in text1
        text3 = render_observation(state, "a3", [], NAMES, content)
        assert "o1" not in text3

    def test_project_status_shown(self, state, content):
        state["project"]["contributed"] = {"wood_bundle": 1}
        text = render_observation(state, "a1", [], NAMES, content)
        assert "beacon" in text.lower()
        assert "wood_bundle" in text

    def test_deterministic_and_in_budget(self, state, content):
        a = render_observation(state, "a1", [], NAMES, content)
        assert a == render_observation(state, "a1", [], NAMES, content)
        assert len(a) < 4000  # ~1k tokens
