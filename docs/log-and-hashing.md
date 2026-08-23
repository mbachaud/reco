# Run Log, Journal, and Hashing Spec

## Canonical form
`reco.engine.hashing.canonical_json`: UTF-8, sorted keys, compact separators
(`,`/`:`), non-ASCII unescaped. Allowed types: dict (string keys), list, str,
int, bool, None. **Floats are rejected** — the simulation is integer-only.
`sha256_hex` = SHA-256 hex digest of the canonical bytes. Pinned by
`tests/test_hashing.py` (spec vector: 28 bytes, `17c8c6f7…`).

## Files per run directory
- `log.jsonl` — append-only chained run log (below)
- `journal.jsonl` — per-agent decision journal
- `checkpoint.json` — atomic (temp+fsync+rename) resume accelerator
- `summary.json`, `report.md`, `report.json` — outputs

## Decision journal
One JSON line per finalized driver outcome:
`{"tick", "agent", "outcome": {"kind": "response"|"error", ...}}`.
Appended + flushed + fsynced BEFORE engine resolution consumes the outcome.
On restart, finalized slots are reused verbatim; only unfinished slots trigger
provider calls. A torn trailing line is truncated on open. Duplicate slots are
an error. **Resume equivalence is exact from input finalization onward.**

## Run log records
First record: `{"t": "manifest", "manifest": {schema_version, kind, seed,
agent_ids, agents (sanitized driver configs), names, content, content_hash}}`.
Then per tick, in order: `obs` (driver agents), `actions` (all agents,
post-parse candidate actions, display names already translated to agent ids),
`parse` (driver agents: PE code + per-action errors), `metrics`,
`events` — each stamped with `"tick"` — followed by:

```
{"t": "tick_commit", "tick", "prev", "record_count", "records_digest",
 "actions_digest", "events_digest", "state_hash"}
```

- `prev` = sha256 of the previous commit record (genesis: of the manifest record)
- `records_digest` = sha256 of the tick's stamped record list
- `actions_digest` / `events_digest` = sha256 of the filtered record lists
- `state_hash` = sha256 of the post-tick state

Write protocol: append records, fsync, append commit, fsync. On open,
anything after the last commit marker is discarded (journal entries are NOT).
Checkpoints publish only after their tick's commit is durable.

## Replay (`reco replay <dir>`)
Provider-free: re-runs the pure engine over logged candidate actions and
asserts every state hash, the full events record (rejections included), and
recomputed metrics. Any divergence names the exact tick.
