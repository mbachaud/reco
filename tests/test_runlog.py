"""Run log: append-only JSONL with chained tick commits.

Per tick: records are appended and fsynced, then a tick_commit record binding
prev-commit hash, record digest/count, candidate-action digest, event digest,
and post-state hash. On open, anything after the last commit marker is
discarded (journaled decision inputs live elsewhere and are NOT discarded).
"""
import json

import pytest

from reco.engine.hashing import sha256_hex
from reco.runner.runlog import IntegrityError, RunLog

MANIFEST = {"schema_version": 1, "seed": 42, "roster": [{"driver": "mock"}]}


def make_records(tag):
    return [
        {"t": "obs", "agent": "a1", "text": f"obs-{tag}"},
        {"t": "actions", "agent": "a1", "actions": [{"verb": "move", "path": [tag]}]},
        {"t": "events", "events": [{"type": "moved", "agent": "a1"}]},
        {"t": "metrics", "gdp": tag},
    ]


@pytest.fixture
def path(tmp_path):
    return tmp_path / "log.jsonl"


def write_two_ticks(path):
    log = RunLog(path)
    log.write_manifest(MANIFEST)
    log.commit_tick(0, make_records(0), state_hash=sha256_hex({"s": 0}))
    log.commit_tick(1, make_records(1), state_hash=sha256_hex({"s": 1}))
    log.close()


class TestRoundTrip:
    def test_manifest_and_ticks_read_back(self, path):
        write_two_ticks(path)
        log = RunLog(path)
        assert log.manifest == MANIFEST
        assert log.last_committed_tick == 1
        ticks = log.read_ticks()
        assert [t for t, _, _ in ticks] == [0, 1]
        _, records, commit = ticks[1]
        assert {"t": "obs", "tick": 1, "agent": "a1", "text": "obs-1"} in records
        assert commit["state_hash"] == sha256_hex({"s": 1})

    def test_commit_requires_manifest(self, path):
        log = RunLog(path)
        with pytest.raises(IntegrityError):
            log.commit_tick(0, make_records(0), state_hash="00")

    def test_ticks_must_ascend(self, path):
        log = RunLog(path)
        log.write_manifest(MANIFEST)
        log.commit_tick(0, make_records(0), state_hash="aa")
        with pytest.raises(IntegrityError):
            log.commit_tick(0, make_records(0), state_hash="aa")


class TestCommitBinding:
    def test_chain_links_to_previous_commit(self, path):
        write_two_ticks(path)
        ticks = RunLog(path).read_ticks()
        _, _, commit0 = ticks[0]
        _, _, commit1 = ticks[1]
        assert commit1["prev"] == sha256_hex(commit0)
        # Genesis links to the manifest record.
        assert commit0["prev"] == sha256_hex({"t": "manifest", "manifest": MANIFEST})

    def test_commit_binds_digests_and_counts(self, path):
        write_two_ticks(path)
        _, records, commit = RunLog(path).read_ticks()[0]
        assert commit["record_count"] == len(records)
        assert commit["records_digest"] == sha256_hex(records)
        actions = [r for r in records if r["t"] == "actions"]
        events = [r for r in records if r["t"] == "events"]
        assert commit["actions_digest"] == sha256_hex(actions)
        assert commit["events_digest"] == sha256_hex(events)


class TestRecovery:
    def test_uncommitted_trailing_records_discarded(self, path):
        write_two_ticks(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": "obs", "tick": 2, "agent": "a1"}) + "\n")
            f.write(json.dumps({"t": "actions", "tick": 2, "agent": "a1"}) + "\n")

        log = RunLog(path)
        assert log.last_committed_tick == 1
        assert [t for t, _, _ in log.read_ticks()] == [0, 1]

    def test_torn_partial_line_discarded(self, path):
        write_two_ticks(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"t": "obs", "tick": 2, "ag')

        log = RunLog(path)
        assert log.last_committed_tick == 1

    def test_can_continue_after_recovery(self, path):
        write_two_ticks(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"t": "obs", "tick": 2, "ag')

        log = RunLog(path)
        log.commit_tick(2, make_records(2), state_hash=sha256_hex({"s": 2}))
        log.close()

        reread = RunLog(path)
        assert reread.last_committed_tick == 2
        reread.verify()

    def test_empty_and_missing_files(self, path):
        assert RunLog(path).manifest is None
        path.touch()
        assert RunLog(path).manifest is None


class TestVerify:
    def test_clean_log_verifies(self, path):
        write_two_ticks(path)
        RunLog(path).verify()

    def test_tampered_record_detected(self, path):
        write_two_ticks(path)
        text = path.read_text(encoding="utf-8")
        assert "obs-0" in text
        path.write_text(text.replace("obs-0", "obs-X"), encoding="utf-8")
        with pytest.raises(IntegrityError):
            RunLog(path).verify()

    def test_tampered_commit_chain_detected(self, path):
        write_two_ticks(path)
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        # Corrupt tick 0's commit record (its own digest fields), keeping tick 1
        # pointing at the old hash -> chain break must be detected.
        for i, line in enumerate(lines):
            rec = json.loads(line)
            if rec.get("t") == "tick_commit" and rec["tick"] == 0:
                rec["state_hash"] = "0" * 64
                lines[i] = json.dumps(rec, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(IntegrityError):
            RunLog(path).verify()
