"""The run loop.

Per tick: render observations, collect decisions (reusing journaled slots),
fsync every finalized outcome to the decision journal BEFORE resolution, parse
into candidate actions (PE_* errors echoed next tick), run the pure engine
step, commit the tick's records to the chained run log. Resume reconstructs
state by replaying committed actions and never re-calls a finalized slot.

Rate-limited drivers back off inside the tick barrier — the whole simulation
pauses rather than idling one provider's agents (idling would bias the run).
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Semaphore

from reco.engine.content import load_content
from reco.engine.hashing import sha256_hex
from reco.engine.mapgen import init_state
from reco.engine.step import step
from reco.gateway.backend import NativeBackend
from reco.gateway.drivers.cli_claude import ClaudeCliDriver
from reco.gateway.drivers.cli_codex import CodexCliDriver
from reco.gateway.drivers.http_openai import HttpOpenAIDriver
from reco.gateway.drivers.mock import MockDriver
from reco.gateway.drivers.scripted import decide_scripted
from reco.gateway.prompts import render_observation, render_static
from reco.runner.checkpoint import save_checkpoint
from reco.runner.journal import DecisionJournal
from reco.runner.metrics import compute_metrics
from reco.runner.naming import seeded_names
from reco.runner.parse import parse_actions
from reco.runner.runlog import RunLog

CHECKPOINT_EVERY = 5
SCHEMA_VERSION = 2
DEFAULT_TIMEOUT_S = 180
DEFAULT_CONCURRENCY = {"anthropic": 3, "openai": 3, "google": 2, "http": 8, "local": 16}
RATE_LIMIT_WAIT_CAP_S = 600
TRANSIENT_RETRIES = 3


def run(config: dict, run_dir) -> dict:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    content = load_content(config["content"])
    agent_ids = [a["id"] for a in config["agents"]]
    names = seeded_names(config["seed"], agent_ids)
    specs = _build_specs(config, run_dir)
    roles = {aid: s["role"] for aid, s in specs.items() if s.get("role")}
    statics = {
        aid: render_static(content, names[aid])
        for aid, s in specs.items()
        if s["kind"] != "scripted"
    }

    log = RunLog(run_dir / "log.jsonl")
    journal = DecisionJournal(run_dir / "journal.jsonl")
    try:
        meteor_tick = config.get("meteor_tick")
        map_cfg = config.get("map", {})
        width = map_cfg.get("width", 12)
        height = map_cfg.get("height", 12)
        if log.manifest is None:
            log.write_manifest({
                "schema_version": SCHEMA_VERSION,
                "kind": "reco_run",
                "seed": config["seed"],
                "agent_ids": agent_ids,
                "agents": _sanitize_agents(config["agents"]),
                "names": names,
                "content": config["content"],
                "content_hash": content["content_hash"],
                "meteor_tick": meteor_tick,
                "map": {"width": width, "height": height},
            })
        else:
            m = log.manifest
            if (
                m["seed"] != config["seed"]
                or m.get("agent_ids", [a["id"] for a in m.get("agents", [])]) != agent_ids
                or m["content_hash"] != content["content_hash"]
                or m.get("meteor_tick") != meteor_tick
            ):
                raise ValueError("config does not match the existing run manifest")

        state = init_state(seed=config["seed"], content=content,
                           agent_ids=agent_ids, meteor_tick=meteor_tick,
                           width=width, height=height)
        complete_tick = None
        prev_events: list[dict] = []
        prev_parse: dict[str, list[dict]] = {}
        for tick, records, commit in log.read_ticks():
            bundles = {r["agent"]: r["actions"] for r in records if r["t"] == "actions"}
            state, _ = step(state, bundles, content)
            if sha256_hex(state) != commit["state_hash"]:
                raise ValueError(f"tick {tick}: log and engine diverge on resume")
            if state["project"]["complete"] and complete_tick is None:
                complete_tick = state["tick"]
            prev_events = next(
                (r["events"] for r in records if r["t"] == "events"), []
            )
            prev_parse = {
                r["agent"]: _feedback(r)
                for r in records
                if r["t"] == "parse"
            }

        name_to_id = {name.lower(): aid for aid, name in names.items()}
        timeout_s = config.get("timeout_s", DEFAULT_TIMEOUT_S)
        semaphores = {
            provider: Semaphore(cap)
            for provider, cap in {**DEFAULT_CONCURRENCY, **config.get("concurrency", {})}.items()
        }

        while not _finished(state) and state["tick"] < config["ticks"]:
            tick = state["tick"]
            observations = {
                aid: render_observation(
                    state, aid, prev_events, names, content,
                    parse_errors=prev_parse.get(aid),
                )
                for aid, s in sorted(specs.items())
                if s["kind"] != "scripted"
            }

            outcomes = dict(journal.finalized(tick))
            pending = [aid for aid in agent_ids if aid not in outcomes]
            inline = [aid for aid in pending if specs[aid]["kind"] != "driver"]
            pooled = [aid for aid in pending if specs[aid]["kind"] == "driver"]

            for aid in inline:
                bundle = decide_scripted(state, aid, specs[aid]["role"], content, roles=roles)
                outcome = {"kind": "response",
                           "text": json.dumps(bundle, ensure_ascii=False)}
                journal.finalize(tick, aid, outcome)
                outcomes[aid] = outcome

            if pooled:
                with ThreadPoolExecutor(max_workers=min(16, len(pooled))) as pool:
                    futures = {
                        aid: pool.submit(
                            _call_driver, specs[aid]["driver"], statics[aid],
                            observations[aid], timeout_s,
                            semaphores.setdefault(
                                specs[aid]["driver"].provider, Semaphore(4)
                            ),
                        )
                        for aid in pooled
                    }
                    for aid, future in futures.items():
                        outcome = future.result()
                        journal.finalize(tick, aid, outcome)
                        outcomes[aid] = outcome

            bundles, parse_records, feedback = {}, [], {}
            for aid in agent_ids:
                outcome = outcomes[aid]
                if outcome["kind"] == "error":
                    bundles[aid] = []
                    record = {"t": "parse", "agent": aid,
                              "code": outcome["code"], "errors": []}
                else:
                    parsed = parse_actions(outcome["text"])
                    bundles[aid] = _translate_names(parsed["actions"], name_to_id)
                    record = {"t": "parse", "agent": aid,
                              "code": parsed["code"], "errors": parsed["errors"]}
                if specs[aid]["kind"] != "scripted":
                    parse_records.append(record)
                    feedback[aid] = _feedback(record)

            new_state, events = step(state, bundles, content)
            closed = {e["offer_id"]: state["offers"][e["offer_id"]]
                      for e in events if e["type"] == "offer_accepted"}
            metrics = compute_metrics(new_state, events, content, closed_offers=closed)
            records = (
                [{"t": "obs", "agent": aid, "text": observations[aid]}
                 for aid in sorted(observations)]
                + [{"t": "actions", "agent": aid, "actions": bundles[aid]}
                   for aid in agent_ids]
                + parse_records
                + [{"t": "metrics", **metrics}]
                + [{"t": "events", "events": events}]
            )
            log.commit_tick(tick, records, state_hash=sha256_hex(new_state))
            state = new_state
            progress = state["project"]["contributed"]
            errors = [f"{aid}:{r['code']}" for r in parse_records
                      for aid in [r["agent"]] if r["code"]]
            print(f"tick {tick}: actions={sum(len(b) for b in bundles.values())} "
                  f"chat={metrics['chat_count']} trades={metrics['trade_count']} "
                  f"project={progress}"
                  + (f" parse_errors={errors}" if errors else ""),
                  flush=True)
            prev_events = events
            prev_parse = feedback
            if state["project"]["complete"] and complete_tick is None:
                complete_tick = state["tick"]
            if (tick + 1) % CHECKPOINT_EVERY == 0:
                save_checkpoint(run_dir / "checkpoint.json", {
                    "tick": log.last_committed_tick,
                    "state": state,
                    "state_hash": sha256_hex(state),
                })

        last = log.last_committed_tick
        meteor = state["meteor"]
        margin = (
            meteor["impact_tick"] - complete_tick
            if meteor["outcome"] == "defended" and complete_tick is not None
            else None
        )
        summary = {
            "ticks_committed": 0 if last is None else last + 1,
            "project_complete": state["project"]["complete"],
            "complete_tick": complete_tick,
            "meteor": {"impact_tick": meteor["impact_tick"],
                       "outcome": meteor["outcome"], "margin": margin},
            "final_state_hash": sha256_hex(state),
            "names": names,
        }
        (run_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary
    finally:
        log.close()
        journal.close()


def _finished(state) -> bool:
    """With a meteor, the run ends at resolution; otherwise at completion."""
    if state["meteor"]["impact_tick"] is not None:
        return state["meteor"]["outcome"] is not None
    return state["project"]["complete"]


def _translate_names(actions: list[dict], name_to_id: dict[str, str]) -> list[dict]:
    """Agents address each other by display name; the engine speaks agent ids."""
    out = []
    for action in actions:
        to = action.get("to")
        if isinstance(to, str) and to.lower() in name_to_id:
            action = {**action, "to": name_to_id[to.lower()]}
        out.append(action)
    return out


def _feedback(parse_record: dict) -> list[dict]:
    feedback = []
    if parse_record["code"]:
        feedback.append({
            "code": parse_record["code"],
            "reason": "your reply produced no usable action array",
        })
    for err in parse_record["errors"]:
        feedback.append({"code": err["code"], "reason": err["reason"]})
    return feedback


def _build_specs(config: dict, run_dir: Path) -> dict[str, dict]:
    backend = NativeBackend()
    specs = {}
    for entry in config["agents"]:
        aid = entry["id"]
        if "role" in entry:
            specs[aid] = {"kind": "scripted", "role": entry["role"]}
            continue
        d = entry["driver"]
        dtype = d["type"]
        if dtype == "mock_scripted":
            specs[aid] = {"kind": "mock_scripted", "role": d["role"]}
        elif dtype == "mock":
            driver = d.get("instance") or MockDriver(d["respond"])
            specs[aid] = {"kind": "driver", "driver": driver, "role": None}
        elif dtype == "http_openai":
            params = {k: v for k, v in d.items() if k not in ("type", "api_key_env")}
            if "api_key_env" in d:
                params["api_key"] = os.environ.get(d["api_key_env"])
            specs[aid] = {"kind": "driver", "driver": HttpOpenAIDriver(**params), "role": None}
        elif dtype == "cli_claude":
            specs[aid] = {"kind": "driver", "driver": ClaudeCliDriver(
                model=d["model"], workspace=run_dir / "workspaces" / aid,
                backend=backend), "role": None}
        elif dtype == "cli_codex":
            specs[aid] = {"kind": "driver", "driver": CodexCliDriver(
                model=d["model"], workspace=run_dir / "workspaces" / aid,
                backend=backend), "role": None}
        else:
            raise ValueError(f"unknown driver type {dtype!r}")
    return specs


def _sanitize_agents(agents: list[dict]) -> list[dict]:
    out = []
    for entry in agents:
        clean = {"id": entry["id"]}
        if "role" in entry:
            clean["role"] = entry["role"]
        if "driver" in entry:
            clean["driver"] = {
                k: v for k, v in entry["driver"].items()
                if isinstance(v, (str, int, float, bool))
            }
        out.append(clean)
    return out


def _call_driver(driver, static: str, observation: str, timeout_s: int,
                 semaphore: Semaphore) -> dict:
    waited = 0
    wait = 5
    transient_left = TRANSIENT_RETRIES
    while True:
        with semaphore:
            result = driver.decide(static, observation, timeout_s)
        if result.error is None:
            return {"kind": "response", "text": result.text,
                    "usage": result.usage, "meta": result.meta}
        if result.error == "timeout":
            return {"kind": "error", "code": "PE_TIMEOUT", "meta": result.meta}
        if result.error == "rate_limit":
            if waited >= RATE_LIMIT_WAIT_CAP_S:
                return {"kind": "error", "code": "PE_DRIVER",
                        "detail": "rate_limit", "meta": result.meta}
            time.sleep(wait)
            waited += wait
            wait = min(wait * 2, 60)
            continue
        if result.error == "transient" and transient_left > 0:
            transient_left -= 1
            time.sleep(1)
            continue
        return {"kind": "error", "code": "PE_DRIVER",
                "detail": result.error, "meta": result.meta}
