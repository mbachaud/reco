"""Render-frame export: replays a run log through the pure engine and captures
one drawable frame per tick — the data feed for the HTML viewer (and any future
viewer transport). Provider-free by construction."""
from pathlib import Path

from reco.engine.content import load_content
from reco.engine.mapgen import init_state
from reco.engine.step import step
from reco.runner.runlog import RunLog

TERRAIN_CODES = {"plains": 0, "forest": 1, "mountain": 2, "water": 3, "desert": 4}


def export_frames(run_dir) -> dict:
    log = RunLog(Path(run_dir) / "log.jsonl")
    manifest = log.manifest
    content = load_content(manifest["content"])
    names = manifest["names"]
    agent_ids = manifest["agent_ids"]
    map_cfg = manifest.get("map", {})
    state = init_state(seed=manifest["seed"], content=content, agent_ids=agent_ids,
                       meteor_tick=manifest.get("meteor_tick"),
                       width=map_cfg.get("width", 12), height=map_cfg.get("height", 12))

    terrain = [
        [TERRAIN_CODES[state["tiles"][f"{x},{y}"]["terrain"]]
         for x in range(state["width"])]
        for y in range(state["height"])
    ]

    frames = []
    for tick, records, commit in log.read_ticks():
        bundles = {r["agent"]: r["actions"] for r in records if r["t"] == "actions"}
        state, events = step(state, bundles, content)
        frames.append(_frame(tick, state, events, names, records))

    return {
        "meta": {
            "run": str(run_dir),
            "seed": manifest["seed"],
            "content": manifest["content"],
            "width": state["width"],
            "height": state["height"],
            "terrain": terrain,
            "names": names,
            "agents": [
                {
                    "id": entry["id"],
                    "name": names.get(entry["id"], entry["id"]),
                    "driver": entry.get("driver", {}).get("type", "scripted"),
                    "model": entry.get("driver", {}).get("model"),
                    "role": entry.get("role") or entry.get("driver", {}).get("role"),
                }
                for entry in manifest["agents"]
            ],
            "project_site": state["project"]["site"],
            "project_needs": state["project"]["needs"],
        },
        "frames": frames,
    }


def _frame(tick, state, events, names, records) -> dict:
    def name(aid):
        return names.get(aid, aid)

    chat = [
        {
            "from": name(e["from"]),
            "to": name(e["to"]) if e.get("to") else None,
            "channel": e["channel"],
            "text": e["text"],
        }
        for e in events
        if e["type"] == "chat"
    ]
    milestones = []
    for e in events:
        if e["type"] == "contributed":
            milestones.append(f"{name(e['agent'])} contributed {e['qty']} {e['item']}")
        elif e["type"] == "built":
            milestones.append(f"{name(e['agent'])} built a {e['building']}")
        elif e["type"] == "offer_accepted":
            milestones.append(f"{name(e['to'])} accepted a trade from {name(e['from'])}")
        elif e["type"] == "project_complete":
            milestones.append("PROJECT COMPLETE")

    metrics_record = next((r for r in records if r["t"] == "metrics"), {})
    metrics = {k: v for k, v in metrics_record.items() if k not in ("t", "tick")}

    return {
        "tick": tick,
        "agents": {
            aid: {
                "pos": a["pos"],
                "calories": a["calories"],
                "inventory": a["inventory"],
            }
            for aid, a in sorted(state["agents"].items())
        },
        "deposits": {
            key: {"kind": t["deposit"]["kind"], "qty": t["deposit"]["qty"]}
            for key, t in sorted(state["tiles"].items())
            if t["deposit"] is not None
        },
        "buildings": {
            key: t["building"]["kind"]
            for key, t in sorted(state["tiles"].items())
            if t["building"] is not None
        },
        "project": {
            "contributed": state["project"]["contributed"],
            "complete": state["project"]["complete"],
        },
        "meteor": dict(state["meteor"]),
        "chat": chat,
        "milestones": milestones,
        "rejections": sum(1 for e in events if e["type"] == "rejected"),
        "metrics": metrics,
    }
