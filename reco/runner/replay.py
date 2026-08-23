"""Provider-free replay: re-run the engine over logged candidate actions and
assert every state hash and event record. This is the integrity check behind
resume, the benchmark audit trail, and (later) the viewer's data feed."""
from pathlib import Path

from reco.engine.content import load_content
from reco.engine.hashing import sha256_hex
from reco.engine.mapgen import init_state
from reco.engine.step import step
from reco.runner.metrics import compute_metrics
from reco.runner.runlog import RunLog


class ReplayError(Exception):
    """Replay diverged from the logged run."""


def replay(run_dir, verify_log: bool = True) -> dict:
    log = RunLog(Path(run_dir) / "log.jsonl")
    manifest = log.manifest
    if manifest is None:
        raise ReplayError(f"no manifest in {run_dir}")
    if verify_log:
        log.verify()
    content = load_content(manifest["content"])
    if content["content_hash"] != manifest["content_hash"]:
        raise ReplayError("content bundle hash does not match the manifest")

    agent_ids = [a["id"] for a in manifest["agents"]]
    map_cfg = manifest.get("map", {})
    state = init_state(seed=manifest["seed"], content=content, agent_ids=agent_ids,
                       meteor_tick=manifest.get("meteor_tick"),
                       width=map_cfg.get("width", 12), height=map_cfg.get("height", 12))
    ticks = 0
    for tick, records, commit in log.read_ticks():
        bundles = {r["agent"]: r["actions"] for r in records if r["t"] == "actions"}
        pre_offers = state["offers"]
        state, events = step(state, bundles, content)
        if sha256_hex(state) != commit["state_hash"]:
            raise ReplayError(f"tick {tick}: replayed state hash diverges")
        logged_events = [r for r in records if r["t"] == "events"]
        if logged_events != [{"t": "events", "tick": tick, "events": events}]:
            raise ReplayError(f"tick {tick}: replayed events diverge")
        logged_metrics = [r for r in records if r["t"] == "metrics"]
        if logged_metrics:
            closed = {e["offer_id"]: pre_offers[e["offer_id"]]
                      for e in events if e["type"] == "offer_accepted"}
            expected = {"t": "metrics", "tick": tick,
                        **compute_metrics(state, events, content, closed_offers=closed)}
            if logged_metrics != [expected]:
                raise ReplayError(f"tick {tick}: replayed metrics diverge")
        ticks += 1
    return {"ticks": ticks, "final_state_hash": sha256_hex(state)}
