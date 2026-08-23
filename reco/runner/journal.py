"""Decision journal: durable driver outcomes.

Every finalized driver outcome (response text or terminal error) is appended
and fsynced BEFORE engine resolution consumes it. On restart, finalized slots
are reused verbatim so only unfinished agents trigger new provider calls.
A torn trailing line from a crash mid-append is truncated on open.
"""
import json
import os


class DecisionJournal:
    def __init__(self, path):
        self._path = path
        self._slots: dict[tuple[int, str], dict] = {}
        self._fh = None
        self._recover()

    def _recover(self) -> None:
        """Load complete records; truncate a torn trailing line if present."""
        if not os.path.exists(self._path):
            return
        valid_end = 0
        with open(self._path, "rb") as f:
            data = f.read()
        pos = 0
        while True:
            nl = data.find(b"\n", pos)
            if nl == -1:
                break
            line = data[pos : nl]
            record = json.loads(line.decode("utf-8"))
            self._slots[(record["tick"], record["agent"])] = record["outcome"]
            pos = nl + 1
            valid_end = pos
        if valid_end < len(data):
            with open(self._path, "r+b") as f:
                f.truncate(valid_end)

    def finalize(self, tick: int, agent_id: str, outcome: dict) -> None:
        key = (tick, agent_id)
        if key in self._slots:
            raise ValueError(f"slot already finalized: tick={tick} agent={agent_id}")
        record = {"tick": tick, "agent": agent_id, "outcome": outcome}
        if self._fh is None:
            self._fh = open(self._path, "a", encoding="utf-8", newline="\n")
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._slots[key] = outcome

    def finalized(self, tick: int) -> dict[str, dict]:
        return {
            agent: outcome
            for (t, agent), outcome in self._slots.items()
            if t == tick
        }

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
