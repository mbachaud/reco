"""Full-content interface: parse specs for new verbs, meteor/skills/balances
in observations, specialization entropy metric."""
import copy

import pytest

from reco.engine.mapgen import init_state
from reco.gateway.prompts import render_observation
from reco.runner.metrics import compute_metrics, specialization_entropy_milli
from reco.runner.parse import parse_actions

NAMES = {"a1": "Ash", "a2": "Brook", "a3": "Cedar"}


class TestParseNewVerbs:
    def test_valid_new_verbs_pass(self):
        raw = """[
          {"verb": "study", "profession": "logging"},
          {"verb": "claim", "x": 3, "y": 4},
          {"verb": "grant", "to": "Brook", "x": 3, "y": 4},
          {"verb": "create_currency", "name": "shells"},
          {"verb": "mint", "currency": "shells", "amount": 100},
          {"verb": "set_prices", "item": "bread", "currency": "shells", "sell": 3},
          {"verb": "stock", "item": "bread", "qty": 5},
          {"verb": "buy", "item": "bread", "qty": 2}
        ]"""
        r = parse_actions(raw)
        assert r["code"] is None and not r["errors"] and len(r["actions"]) == 8

    def test_bad_args_rejected_individually(self):
        raw = '[{"verb": "claim", "x": "three", "y": 4}, {"verb": "mint", "currency": "shells"}]'
        r = parse_actions(raw)
        assert [e["code"] for e in r["errors"]] == ["PE_SCHEMA", "PE_SCHEMA"]

    def test_offer_credits_validated(self):
        r = parse_actions('[{"verb": "offer", "to": "Brook", "give": {}, '
                          '"give_credits": {"shells": 5}, "want": {"wood": 1}}]')
        assert r["code"] is None and not r["errors"]
        r = parse_actions('[{"verb": "offer", "to": "Brook", "give": {}, '
                          '"give_credits": "five", "want": {}}]')
        assert r["errors"]


class TestObservationAdditions:
    @pytest.fixture
    def fstate(self, content):
        c = copy.deepcopy(content)
        c["professions"] = {"logging": {}}
        state = init_state(seed=42, content=c, agent_ids=list(NAMES), meteor_tick=50)
        return c, state

    def test_meteor_countdown_shown(self, fstate):
        c, state = fstate
        state["tick"] = 30
        text = render_observation(state, "a1", [], NAMES, c)
        assert "METEOR" in text and "20" in text

    def test_skills_and_balances_shown(self, fstate):
        c, state = fstate
        state["agents"]["a1"]["skills"] = {"logging": {"xp": 150, "level": 2}}
        state["agents"]["a1"]["balances"] = {"shells": 40}
        text = render_observation(state, "a1", [], NAMES, c)
        assert "logging" in text and "2" in text
        assert "shells" in text and "40" in text

    def test_shop_on_tile_shown(self, fstate):
        c, state = fstate
        pos = state["agents"]["a1"]["pos"]
        state["tiles"][f"{pos[0]},{pos[1]}"]["building"] = {
            "kind": "shop", "owner": "a2", "stock": {"berries": 5},
            "prices": {"berries": {"currency": "shells", "sell": 2}},
        }
        text = render_observation(state, "a1", [], NAMES, c)
        assert "berries" in text and "shells" in text and "Brook" in text


class TestSpecializationEntropy:
    def test_uniform_is_high_specialized_is_low(self):
        specialized = {"a1": {"logging": {"xp": 100, "level": 2}},
                       "a2": {"mining": {"xp": 100, "level": 2}}}
        generalist = {"a1": {"logging": {"xp": 50, "level": 1},
                             "mining": {"xp": 50, "level": 1}},
                      "a2": {"logging": {"xp": 50, "level": 1},
                             "mining": {"xp": 50, "level": 1}}}
        assert specialization_entropy_milli(specialized) < specialization_entropy_milli(generalist)

    def test_empty_is_zero(self):
        assert specialization_entropy_milli({}) == 0

    def test_metric_included_when_skills_exist(self, state, content):
        state["agents"]["a1"]["skills"] = {"logging": {"xp": 100, "level": 2}}
        m = compute_metrics(state, [], content)
        assert "specialization_entropy_milli" in m
