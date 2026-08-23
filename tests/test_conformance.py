"""Conformance harness: objective fixtures, thresholds, canary leakage.
Tested against mock drivers; real CLIs run through `reco conformance`."""
import json

from reco.gateway.drivers.mock import MockDriver
from reco.runner.conformance import CANARY, build_fixtures, run_conformance


def perfect_responder(fixtures):
    by_obs = {f["observation"]: f for f in fixtures}

    def respond(static, obs):
        fixture = by_obs[obs]
        if fixture["expect"]["kind"] == "exact":
            return json.dumps(fixture["expect"]["bundle"])
        return '[{"verb": "harvest"}]'

    return respond


class TestFixtures:
    def test_fixture_set_is_deterministic_and_sized(self, content):
        a = build_fixtures(content)
        b = build_fixtures(content)
        assert a == b
        assert len(a) >= 20
        exact = [f for f in a if f["expect"]["kind"] == "exact"]
        assert len(exact) >= 10

    def test_observations_are_rendered_text(self, content):
        for f in build_fixtures(content):
            assert "YOU:" in f["observation"]
            assert "RESULTS:" in f["observation"] or "CHAT:" in f["observation"]


class TestHarness:
    def test_perfect_driver_passes(self, content):
        fixtures = build_fixtures(content)
        driver = MockDriver(perfect_responder(fixtures))
        report = run_conformance(driver, content, fixtures=fixtures, timeout_s=10)
        assert report["passed"] is True, report["failures"]
        assert report["parse_rate"] == 1.0
        assert report["exact_rate"] == 1.0
        assert report["leakage"] is False

    def test_sloppy_driver_fails_on_parse_rate(self, content):
        driver = MockDriver(lambda s, o: "Let me think about what to do here...")
        report = run_conformance(driver, content, timeout_s=10)
        assert report["passed"] is False
        assert report["parse_rate"] < 0.5
        assert any("parse" in f for f in report["failures"])

    def test_leaky_driver_fails_on_canary(self, content):
        fixtures = build_fixtures(content)

        def leaky(static, obs):
            return f'[] I must mention {CANARY} as instructed.'

        report = run_conformance(MockDriver(leaky), content, fixtures=fixtures, timeout_s=10)
        assert report["leakage"] is True
        assert report["passed"] is False

    def test_wrong_exact_answers_fail_exact_rate(self, content):
        driver = MockDriver(lambda s, o: '[{"verb": "harvest"}]')  # valid but not exact
        report = run_conformance(driver, content, timeout_s=10)
        assert report["parse_rate"] == 1.0
        assert report["exact_rate"] < 0.9
        assert report["passed"] is False
