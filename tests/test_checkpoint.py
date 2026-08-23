"""Checkpoints publish atomically: a crash mid-save must never destroy the
previous good checkpoint, and stray temp files must never be mistaken for one.
"""
import pytest

from reco.runner.checkpoint import CheckpointError, load_checkpoint, save_checkpoint


@pytest.fixture
def path(tmp_path):
    return tmp_path / "checkpoint.json"


class TestSaveLoad:
    def test_round_trip(self, path):
        payload = {"tick": 7, "state": {"agents": {"a1": {"cal": 900}}}, "runner": {"next": 8}}
        save_checkpoint(path, payload)
        assert load_checkpoint(path) == payload

    def test_overwrite_returns_latest(self, path):
        save_checkpoint(path, {"tick": 1})
        save_checkpoint(path, {"tick": 2})
        assert load_checkpoint(path) == {"tick": 2}

    def test_no_temp_files_left_behind(self, path):
        save_checkpoint(path, {"tick": 1})
        save_checkpoint(path, {"tick": 2})
        assert [p.name for p in path.parent.iterdir()] == [path.name]

    def test_missing_returns_none(self, path):
        assert load_checkpoint(path) is None

    def test_unicode_round_trips(self, path):
        save_checkpoint(path, {"name": "Béatrice — 世界"})
        assert load_checkpoint(path) == {"name": "Béatrice — 世界"}


class TestCrashSafety:
    def test_corrupt_checkpoint_raises(self, path):
        path.write_text('{"tick": 1, "sta', encoding="utf-8")
        with pytest.raises(CheckpointError):
            load_checkpoint(path)

    def test_leftover_temp_does_not_shadow_real_checkpoint(self, path):
        save_checkpoint(path, {"tick": 5})
        # Simulate a crash mid-save on a later attempt: temp written, no rename.
        (path.parent / (path.name + ".tmp")).write_text('{"tick": 6', encoding="utf-8")
        assert load_checkpoint(path) == {"tick": 5}
