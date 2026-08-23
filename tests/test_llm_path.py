"""Driver-backed runs: the full render -> respond -> parse -> journal ->
resolve pipeline, exercised with zero provider quota via mock drivers."""
import json

from reco.runner.orchestrator import run
from reco.runner.replay import replay
from reco.runner.runlog import RunLog


def mock_scripted_config(ticks=30, seed=42):
    return {
        "seed": seed,
        "ticks": ticks,
        "content": "slice",
        "agents": [
            {"id": "a1", "driver": {"type": "mock_scripted", "role": "wood"}},
            {"id": "a2", "driver": {"type": "mock_scripted", "role": "stone"}},
            {"id": "a3", "driver": {"type": "mock_scripted", "role": "meal"}},
        ],
    }


class TestMockScriptedPipeline:
    def test_completes_beacon_through_text_pipeline(self, tmp_path):
        summary = run(mock_scripted_config(), tmp_path / "r1")
        assert summary["project_complete"] is True

    def test_observations_and_parse_records_logged(self, tmp_path):
        run(mock_scripted_config(ticks=3), tmp_path / "r1")
        _, records, _ = RunLog(tmp_path / "r1" / "log.jsonl").read_ticks()[0]
        obs = [r for r in records if r["t"] == "obs"]
        assert len(obs) == 3
        assert any("MAP" in r["text"] for r in obs)
        journal_lines = (tmp_path / "r1" / "journal.jsonl").read_text(encoding="utf-8")
        assert '"kind": "response"' in journal_lines or '"kind":"response"' in journal_lines

    def test_replay_and_resume(self, tmp_path):
        run(mock_scripted_config(ticks=4), tmp_path / "r1")
        run(mock_scripted_config(), tmp_path / "r1")
        replay(tmp_path / "r1")
        fresh = run(mock_scripted_config(), tmp_path / "fresh")
        resumed = json.loads((tmp_path / "r1" / "summary.json").read_text(encoding="utf-8"))
        assert resumed["final_state_hash"] == fresh["final_state_hash"]


class TestDriverBuild:
    def test_api_key_env_resolved(self, monkeypatch, tmp_path):
        from reco.runner.orchestrator import _build_specs

        monkeypatch.setenv("TEST_RECO_KEY", "sk-test-123")
        specs = _build_specs({
            "agents": [{"id": "a1", "driver": {
                "type": "http_openai", "base_url": "http://x/v1",
                "model": "m", "api_key_env": "TEST_RECO_KEY"}}],
        }, tmp_path)
        assert specs["a1"]["driver"].api_key == "sk-test-123"


class TestMalformedResponses:
    def test_parse_error_echoed_next_tick_and_run_survives(self, tmp_path):
        calls = {"n": 0}

        def flaky(static, obs):
            calls["n"] += 1
            if calls["n"] == 1:
                return "I shall gather the wood at once, my friends!"
            return "[]"

        config = {
            "seed": 42,
            "ticks": 3,
            "content": "slice",
            "agents": [
                {"id": "a1", "driver": {"type": "mock", "respond": flaky}},
                {"id": "a2", "driver": {"type": "mock", "respond": lambda s, o: "[]"}},
            ],
        }
        run(config, tmp_path / "r1")
        log = RunLog(tmp_path / "r1" / "log.jsonl")
        ticks = log.read_ticks()

        tick0 = ticks[0][1]
        parse0 = next(r for r in tick0 if r["t"] == "parse" and r["agent"] == "a1")
        assert parse0["code"] == "PE_MALFORMED"
        a1_actions = next(r for r in tick0 if r["t"] == "actions" and r["agent"] == "a1")
        assert a1_actions["actions"] == []

        tick1_obs = next(
            r for r in ticks[1][1] if r["t"] == "obs" and r["agent"] == "a1"
        )
        assert "PE_MALFORMED" in tick1_obs["text"]
        log.verify()
        replay(tmp_path / "r1")

    def test_display_names_translated_to_agent_ids(self, tmp_path):
        from reco.runner.naming import seeded_names

        names = seeded_names(42, ["a1", "a2"])
        config = {
            "seed": 42,
            "ticks": 1,
            "content": "slice",
            "agents": [
                {"id": "a1", "driver": {"type": "mock", "respond":
                    lambda s, o: json.dumps([
                        {"verb": "dm", "to": names["a2"], "text": "hello friend"}
                    ])}},
                {"id": "a2", "driver": {"type": "mock", "respond": lambda s, o: "[]"}},
            ],
        }
        run(config, tmp_path / "r1")
        _, records, _ = RunLog(tmp_path / "r1" / "log.jsonl").read_ticks()[0]
        events = next(r for r in records if r["t"] == "events")["events"]
        dm = next(e for e in events if e["type"] == "chat")
        assert dm["to"] == "a2" and dm["from"] == "a1"

    def test_timeout_outcome_idles_agent(self, tmp_path):
        class SlowMock:
            def __init__(self):
                self.provider = "local"
                self.name = "slow"

            def decide(self, static, obs, timeout_s):
                from reco.gateway.drivers.base import DriverResult
                return DriverResult(error="timeout")

        config = {
            "seed": 42,
            "ticks": 2,
            "content": "slice",
            "agents": [
                {"id": "a1", "driver": {"type": "mock", "instance": SlowMock()}},
                {"id": "a2", "driver": {"type": "mock", "respond": lambda s, o: "[]"}},
            ],
        }
        run(config, tmp_path / "r1")
        _, records, _ = RunLog(tmp_path / "r1" / "log.jsonl").read_ticks()[0]
        parse = next(r for r in records if r["t"] == "parse" and r["agent"] == "a1")
        assert parse["code"] == "PE_TIMEOUT"
        replay(tmp_path / "r1")
