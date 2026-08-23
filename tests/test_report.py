"""Report generation: per-tick metrics logged and replay-verified, per-agent
character table with provider mapping and format compliance."""
import json

from reco.runner.orchestrator import run
from reco.runner.replay import replay
from reco.runner.report import generate_report
from reco.runner.runlog import RunLog

CONFIG = {
    "seed": 42,
    "ticks": 15,
    "content": "slice",
    "agents": [
        {"id": "a1", "driver": {"type": "mock_scripted", "role": "wood"}},
        {"id": "a2", "driver": {"type": "mock_scripted", "role": "stone"}},
        {"id": "a3", "driver": {"type": "mock_scripted", "role": "meal"}},
    ],
}


class TestMetricsInLog:
    def test_every_tick_has_metrics_record(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        for _, records, _ in RunLog(tmp_path / "r1" / "log.jsonl").read_ticks():
            metrics = [r for r in records if r["t"] == "metrics"]
            assert len(metrics) == 1
            assert "production_value" in metrics[0]

    def test_replay_verifies_metrics(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        replay(tmp_path / "r1")  # must not raise: metrics recomputed and compared


class TestReport:
    def test_report_files_written(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        report = generate_report(tmp_path / "r1")
        assert (tmp_path / "r1" / "report.md").exists()
        assert (tmp_path / "r1" / "report.json").exists()
        assert report["project_complete"] is True

    def test_character_table_and_compliance(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        report = generate_report(tmp_path / "r1")
        agents = {a["id"]: a for a in report["agents"]}
        assert agents["a1"]["name"]
        assert agents["a1"]["driver"] == "mock_scripted"
        assert agents["a1"]["format_compliance_milli"] == 1000
        assert agents["a1"]["contributions"] >= 1
        md = (tmp_path / "r1" / "report.md").read_text(encoding="utf-8")
        assert agents["a1"]["name"] in md
        assert "beacon" in md.lower()

    def test_timeline_totals(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        report = generate_report(tmp_path / "r1")
        assert report["totals"]["production_value"] > 0
        assert report["totals"]["trade_count"] >= 1  # the gift trades
        assert len(report["timeline"]) == report["ticks_committed"]
