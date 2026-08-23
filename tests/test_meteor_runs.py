"""Meteor-configured runs: the loop runs to meteor resolution, the summary
carries the headline (defended + margin reported separately), replay stays
provider-free."""
from reco.runner.orchestrator import run
from reco.runner.replay import replay
from reco.runner.report import generate_report


def config(meteor_tick, ticks=30):
    return {
        "seed": 42,
        "ticks": ticks,
        "content": "slice",
        "meteor_tick": meteor_tick,
        "agents": [
            {"id": "a1", "role": "wood"},
            {"id": "a2", "role": "stone"},
            {"id": "a3", "role": "meal"},
        ],
    }


class TestDefended:
    def test_defended_with_margin(self, tmp_path):
        # scripted trio completes the beacon at tick 9; meteor at 15
        summary = run(config(15), tmp_path / "r1")
        assert summary["meteor"]["outcome"] == "defended"
        assert summary["complete_tick"] == 9
        assert summary["meteor"]["margin"] == 6
        replay(tmp_path / "r1")

    def test_run_continues_past_completion_until_resolution(self, tmp_path):
        summary = run(config(15), tmp_path / "r1")
        assert summary["ticks_committed"] == 15

    def test_report_carries_headline(self, tmp_path):
        run(config(15), tmp_path / "r1")
        report = generate_report(tmp_path / "r1")
        assert report["meteor"]["outcome"] == "defended"
        assert report["meteor"]["margin"] == 6
        md = (tmp_path / "r1" / "report.md").read_text(encoding="utf-8")
        assert "DEFENDED" in md


class TestImpact:
    def test_impact_ends_run(self, tmp_path):
        summary = run(config(5), tmp_path / "r1")
        assert summary["meteor"]["outcome"] == "impact"
        assert summary["meteor"]["margin"] is None
        assert summary["ticks_committed"] == 5
        replay(tmp_path / "r1")
