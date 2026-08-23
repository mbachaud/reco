"""Append-only JSONL run log with chained tick commits.

Write protocol per tick: append this tick's records, fsync, then append a
tick_commit record binding the previous commit's hash, the record digest and
count, the candidate-action digest, the event digest, and the post-state
hash — then fsync again. On open, everything after the last commit marker
(complete or torn) is discarded; decision-journal inputs live in a separate
file and are never discarded.
"""
import json
import os

from reco.engine.hashing import sha256_hex


class IntegrityError(Exception):
    """Run log violates the commit-chain contract."""


class RunLog:
    def __init__(self, path):
        self._path = path
        self._fh = None
        self.manifest: dict | None = None
        self._manifest_record: dict | None = None
        self._ticks: list[tuple[int, list[dict], dict]] = []
        self._prev_hash: str | None = None
        self._recover()

    @property
    def last_committed_tick(self) -> int | None:
        return self._ticks[-1][0] if self._ticks else None

    def _recover(self) -> None:
        if not os.path.exists(self._path):
            return
        with open(self._path, "rb") as f:
            data = f.read()
        pending: list[dict] = []
        valid_end = 0
        pos = 0
        while True:
            nl = data.find(b"\n", pos)
            if nl == -1:
                break
            record = json.loads(data[pos:nl].decode("utf-8"))
            pos = nl + 1
            kind = record.get("t")
            if kind == "manifest":
                self._manifest_record = record
                self.manifest = record["manifest"]
                self._prev_hash = sha256_hex(record)
                valid_end = pos
            elif kind == "tick_commit":
                self._ticks.append((record["tick"], pending, record))
                pending = []
                self._prev_hash = sha256_hex(record)
                valid_end = pos
            else:
                pending.append(record)
        if valid_end < len(data):
            with open(self._path, "r+b") as f:
                f.truncate(valid_end)

    def _append(self, record: dict) -> None:
        if self._fh is None:
            self._fh = open(self._path, "a", encoding="utf-8", newline="\n")
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _fsync(self) -> None:
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def write_manifest(self, manifest: dict) -> None:
        if self.manifest is not None:
            raise IntegrityError("manifest already written")
        record = {"t": "manifest", "manifest": manifest}
        self._append(record)
        self._fsync()
        self._manifest_record = record
        self.manifest = manifest
        self._prev_hash = sha256_hex(record)

    def commit_tick(self, tick: int, records: list[dict], *, state_hash: str) -> None:
        if self.manifest is None:
            raise IntegrityError("cannot commit a tick before the manifest")
        last = self.last_committed_tick
        if last is not None and tick <= last:
            raise IntegrityError(f"tick {tick} does not ascend past {last}")

        stamped = [{**r, "tick": tick} for r in records]
        for record in stamped:
            self._append(record)
        self._fsync()

        commit = {
            "t": "tick_commit",
            "tick": tick,
            "prev": self._prev_hash,
            "record_count": len(stamped),
            "records_digest": sha256_hex(stamped),
            "actions_digest": sha256_hex([r for r in stamped if r["t"] == "actions"]),
            "events_digest": sha256_hex([r for r in stamped if r["t"] == "events"]),
            "state_hash": state_hash,
        }
        self._append(commit)
        self._fsync()
        self._ticks.append((tick, stamped, commit))
        self._prev_hash = sha256_hex(commit)

    def read_ticks(self) -> list[tuple[int, list[dict], dict]]:
        return list(self._ticks)

    def verify(self) -> None:
        prev = (
            sha256_hex(self._manifest_record)
            if self._manifest_record is not None
            else None
        )
        for tick, records, commit in self._ticks:
            if commit["prev"] != prev:
                raise IntegrityError(f"tick {tick}: broken commit chain")
            if commit["record_count"] != len(records):
                raise IntegrityError(f"tick {tick}: record count mismatch")
            if commit["records_digest"] != sha256_hex(records):
                raise IntegrityError(f"tick {tick}: records digest mismatch")
            actions = [r for r in records if r["t"] == "actions"]
            if commit["actions_digest"] != sha256_hex(actions):
                raise IntegrityError(f"tick {tick}: actions digest mismatch")
            events = [r for r in records if r["t"] == "events"]
            if commit["events_digest"] != sha256_hex(events):
                raise IntegrityError(f"tick {tick}: events digest mismatch")
            prev = sha256_hex(commit)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
