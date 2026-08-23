"""Atomic checkpoint publish: write temp, fsync, then os.replace.

A checkpoint is published only after its tick's commit is durable in the run
log; resume loads it and verifies against the commit chain (orchestrator's
job — this module only guarantees the file is all-or-nothing).
"""
import json
import os


class CheckpointError(Exception):
    """Checkpoint file exists but cannot be read."""


def save_checkpoint(path, payload: dict) -> None:
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_checkpoint(path) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CheckpointError(f"corrupt checkpoint at {path}: {exc}") from exc
