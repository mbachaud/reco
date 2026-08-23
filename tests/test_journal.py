"""Decision journal: every finalized driver outcome is durable on disk before
engine resolution consumes it. On restart, finalized slots are reused verbatim
and a torn trailing write (crash mid-append) is discarded cleanly.
"""
import pytest

from reco.runner.journal import DecisionJournal


@pytest.fixture
def path(tmp_path):
    return tmp_path / "journal.jsonl"


class TestFinalize:
    def test_read_back_same_instance(self, path):
        j = DecisionJournal(path)
        j.finalize(3, "a1", {"kind": "response", "text": "[]"})
        assert j.finalized(3) == {"a1": {"kind": "response", "text": "[]"}}

    def test_survives_reopen(self, path):
        j = DecisionJournal(path)
        j.finalize(3, "a1", {"kind": "response", "text": "[]"})
        j.finalize(3, "a2", {"kind": "error", "code": "PE_TIMEOUT"})
        j.close()

        j2 = DecisionJournal(path)
        assert j2.finalized(3) == {
            "a1": {"kind": "response", "text": "[]"},
            "a2": {"kind": "error", "code": "PE_TIMEOUT"},
        }

    def test_scoped_to_tick(self, path):
        j = DecisionJournal(path)
        j.finalize(1, "a1", {"kind": "response", "text": "x"})
        j.finalize(2, "a1", {"kind": "response", "text": "y"})
        assert j.finalized(1) == {"a1": {"kind": "response", "text": "x"}}
        assert j.finalized(2) == {"a1": {"kind": "response", "text": "y"}}
        assert j.finalized(3) == {}

    def test_duplicate_slot_rejected(self, path):
        j = DecisionJournal(path)
        j.finalize(1, "a1", {"kind": "response", "text": "x"})
        with pytest.raises(ValueError):
            j.finalize(1, "a1", {"kind": "response", "text": "again"})

    def test_unicode_round_trips(self, path):
        j = DecisionJournal(path)
        j.finalize(1, "a1", {"kind": "response", "text": "héllo — 世界"})
        j.close()
        assert DecisionJournal(path).finalized(1)["a1"]["text"] == "héllo — 世界"


class TestTornWriteRecovery:
    def test_torn_trailing_line_discarded(self, path):
        j = DecisionJournal(path)
        j.finalize(1, "a1", {"kind": "response", "text": "ok"})
        j.close()
        # Simulate a crash mid-append: an incomplete record with no newline.
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"tick": 1, "agent": "a2", "outco')

        j2 = DecisionJournal(path)
        assert j2.finalized(1) == {"a1": {"kind": "response", "text": "ok"}}

    def test_finalize_after_torn_open_writes_clean_record(self, path):
        j = DecisionJournal(path)
        j.finalize(1, "a1", {"kind": "response", "text": "ok"})
        j.close()
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"torn')

        j2 = DecisionJournal(path)
        j2.finalize(1, "a2", {"kind": "response", "text": "late"})
        j2.close()

        j3 = DecisionJournal(path)
        assert j3.finalized(1) == {
            "a1": {"kind": "response", "text": "ok"},
            "a2": {"kind": "response", "text": "late"},
        }

    def test_empty_file_ok(self, path):
        path.touch()
        assert DecisionJournal(path).finalized(1) == {}

    def test_missing_file_ok(self, path):
        assert DecisionJournal(path).finalized(1) == {}
