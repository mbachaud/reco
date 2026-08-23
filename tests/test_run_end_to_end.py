"""End-to-end run loop: scripted run produces a verifiable chained log,
provider-free replay reproduces every state hash, resume reuses journaled
decisions and produces the identical hash sequence as an uninterrupted run."""
import json

import pytest

from reco.runner.journal import DecisionJournal
from reco.runner.orchestrator import run
from reco.runner.replay import ReplayError, replay
from reco.runner.runlog import RunLog

CONFIG = {
    "seed": 42,
    "ticks": 30,
    "content": "slice",
    "agents": [
        {"id": "a1", "role": "wood"},
        {"id": "a2", "role": "stone"},
        {"id": "a3", "role": "meal"},
    ],
}


def hashes(run_dir):
    return [c["state_hash"] for _, _, c in RunLog(run_dir / "log.jsonl").read_ticks()]


class TestRun:
    def test_scripted_run_completes_and_verifies(self, tmp_path):
        summary = run(CONFIG, tmp_path / "r1")
        assert summary["project_complete"] is True
        assert summary["complete_tick"] == 9
        log = RunLog(tmp_path / "r1" / "log.jsonl")
        log.verify()
        assert log.manifest["seed"] == 42
        assert log.manifest["content_hash"]
        assert (tmp_path / "r1" / "summary.json").exists()

    def test_replay_reproduces_all_hashes(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        report = replay(tmp_path / "r1")
        assert report["ticks"] > 0
        assert report["final_state_hash"] == hashes(tmp_path / "r1")[-1]

    def test_replay_detects_tampered_actions(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        log_path = tmp_path / "r1" / "log.jsonl"
        lines = log_path.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines:
            rec = json.loads(line)
            if rec.get("t") == "actions" and rec["tick"] == 2 and rec["actions"]:
                rec["actions"] = []
                line = json.dumps(rec, ensure_ascii=False)
            out.append(line)
        log_path.write_text("\n".join(out) + "\n", encoding="utf-8")
        with pytest.raises(ReplayError):
            replay(tmp_path / "r1", verify_log=False)


class TestResume:
    def test_resume_matches_uninterrupted_run(self, tmp_path):
        run({**CONFIG, "ticks": 4}, tmp_path / "interrupted")
        run(CONFIG, tmp_path / "interrupted")  # resume to completion
        run(CONFIG, tmp_path / "fresh")
        assert hashes(tmp_path / "interrupted") == hashes(tmp_path / "fresh")

    def test_resume_reuses_journaled_decisions(self, tmp_path):
        run({**CONFIG, "ticks": 4}, tmp_path / "r1")
        # Simulate a crash after one decision of tick 4 was finalized but
        # before the tick committed: pre-finalize a1 with an empty bundle the
        # bot would never produce. Resume must reuse it verbatim.
        j = DecisionJournal(tmp_path / "r1" / "journal.jsonl")
        j.finalize(4, "a1", {"kind": "response", "text": "[]"})
        j.close()

        run(CONFIG, tmp_path / "r1")
        log = RunLog(tmp_path / "r1" / "log.jsonl")
        tick4 = next(records for t, records, _ in log.read_ticks() if t == 4)
        a1_actions = next(r for r in tick4 if r["t"] == "actions" and r["agent"] == "a1")
        assert a1_actions["actions"] == []
        log.verify()
        replay(tmp_path / "r1")

    def test_resume_rejects_mismatched_config(self, tmp_path):
        run({**CONFIG, "ticks": 4}, tmp_path / "r1")
        with pytest.raises(ValueError):
            run({**CONFIG, "seed": 43}, tmp_path / "r1")


class TestRandomFuzz:
    def test_random_run_replays_clean(self, tmp_path):
        config = {
            "seed": 7,
            "ticks": 25,
            "content": "slice",
            "agents": [{"id": a, "role": "random"} for a in ["a1", "a2", "a3"]],
        }
        summary = run(config, tmp_path / "rf")
        assert summary["ticks_committed"] == 25
        RunLog(tmp_path / "rf" / "log.jsonl").verify()
        replay(tmp_path / "rf")
