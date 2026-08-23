"""Run report: headline result, character table (display name -> driver/
provider/model for human reviewers), per-agent stats, metrics timeline."""
import json
from pathlib import Path

from reco.engine.content import load_content
from reco.engine.mapgen import init_state
from reco.engine.step import step
from reco.runner.metrics import value_table
from reco.runner.runlog import RunLog

PROVIDERS = {
    "cli_claude": "anthropic", "cli_codex": "openai", "http_openai": "http",
    "mock": "local", "mock_scripted": "local", "scripted": "local",
}


def generate_report(run_dir) -> dict:
    run_dir = Path(run_dir)
    log = RunLog(run_dir / "log.jsonl")
    manifest = log.manifest
    content = load_content(manifest["content"])
    values = value_table(content)
    names = manifest.get("names", {})

    agents = {}
    for entry in manifest["agents"]:
        aid = entry["id"]
        driver = entry.get("driver", {}).get("type", "scripted")
        agents[aid] = {
            "id": aid,
            "name": names.get(aid, aid),
            "driver": driver,
            "provider": PROVIDERS.get(driver, "unknown"),
            "model": entry.get("driver", {}).get("model"),
            "role": entry.get("role") or entry.get("driver", {}).get("role"),
            "actions": 0, "rejections": 0, "contributions": 0,
            "parse_ok": 0, "parse_total": 0,
        }

    agent_ids = manifest["agent_ids"]
    map_cfg = manifest.get("map", {})
    state = init_state(seed=manifest["seed"], content=content, agent_ids=agent_ids,
                       meteor_tick=manifest.get("meteor_tick"),
                       width=map_cfg.get("width", 12), height=map_cfg.get("height", 12))
    timeline = []
    complete_tick = None
    for tick, records, commit in log.read_ticks():
        for r in records:
            if r["t"] == "actions":
                agents[r["agent"]]["actions"] += len(r["actions"])
            elif r["t"] == "parse":
                agents[r["agent"]]["parse_total"] += 1
                if r["code"] is None:
                    agents[r["agent"]]["parse_ok"] += 1
            elif r["t"] == "metrics":
                timeline.append({k: v for k, v in r.items() if k not in ("t",)})
            elif r["t"] == "events":
                for e in r["events"]:
                    if e["type"] == "rejected":
                        agents[e["agent"]]["rejections"] += 1
                    elif e["type"] == "contributed":
                        agents[e["agent"]]["contributions"] += e["qty"]
        bundles = {r["agent"]: r["actions"] for r in records if r["t"] == "actions"}
        state, _ = step(state, bundles, content)
        if state["project"]["complete"] and complete_tick is None:
            complete_tick = state["tick"]

    for aid, row in agents.items():
        total = row.pop("parse_total")
        ok = row.pop("parse_ok")
        row["format_compliance_milli"] = 1000 * ok // total if total else 1000
        inv = state["agents"][aid]["inventory"]
        row["final_wealth"] = sum(values.get(i, 1) * q for i, q in inv.items())

    metric_keys = ["production_value", "trade_count", "trade_volume",
                   "chat_count", "rejection_count", "contributions"]
    totals = {k: sum(t.get(k, 0) for t in timeline) for k in metric_keys}

    meteor = state["meteor"]
    margin = (
        meteor["impact_tick"] - complete_tick
        if meteor["outcome"] == "defended" and complete_tick is not None
        else None
    )
    last = log.last_committed_tick
    report = {
        "meteor": {"impact_tick": meteor["impact_tick"],
                   "outcome": meteor["outcome"], "margin": margin},
        "seed": manifest["seed"],
        "content": manifest["content"],
        "ticks_committed": 0 if last is None else last + 1,
        "project_kind": state["project"]["kind"],
        "project_complete": state["project"]["complete"],
        "complete_tick": complete_tick,
        "project_contributed": state["project"]["contributed"],
        "project_needs": state["project"]["needs"],
        "agents": [agents[aid] for aid in agent_ids],
        "totals": totals,
        "timeline": timeline,
    }
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "report.md").write_text(_markdown(report), encoding="utf-8")
    return report


def _markdown(r) -> str:
    project = (
        f"COMPLETE at tick {r['complete_tick']}"
        if r["project_complete"]
        else f"incomplete ({r['project_contributed']} of {r['project_needs']})"
    )
    meteor = r.get("meteor", {})
    if meteor.get("outcome") == "defended":
        headline = f"**METEOR DEFENDED** (margin: {meteor['margin']} ticks, reported separately)"
    elif meteor.get("outcome") == "impact":
        headline = "**METEOR IMPACT — civilization failed**"
    elif meteor.get("impact_tick") is not None:
        headline = f"meteor pending (impact tick {meteor['impact_tick']})"
    else:
        headline = "no meteor configured"
    lines = [
        "# Reco Run Report",
        "",
        f"- Seed: {r['seed']}  |  Content: {r['content']}  |  Ticks: {r['ticks_committed']}",
        f"- {headline}",
        f"- **Project ({r.get('project_kind', 'project')}): {project}**",
        "",
        "## Characters",
        "",
        "| Name | Driver | Provider | Model | Role |",
        "|---|---|---|---|---|",
    ]
    for a in r["agents"]:
        lines.append(
            f"| {a['name']} | {a['driver']} | {a['provider']} | "
            f"{a['model'] or '-'} | {a['role'] or '-'} |"
        )
    lines += [
        "",
        "## Agent stats",
        "",
        "| Name | Actions | Rejections | Compliance | Contributions | Final wealth |",
        "|---|---|---|---|---|---|",
    ]
    for a in r["agents"]:
        lines.append(
            f"| {a['name']} | {a['actions']} | {a['rejections']} | "
            f"{a['format_compliance_milli'] / 10:.1f}% | {a['contributions']} | "
            f"{a['final_wealth']} |"
        )
    t = r["totals"]
    lines += [
        "",
        "## Totals",
        "",
        f"- Production value: {t['production_value']}",
        f"- Trades: {t['trade_count']} (volume {t['trade_volume']})",
        f"- Chat messages: {t['chat_count']}",
        f"- Rejections: {t['rejection_count']}",
        f"- Project contributions: {t['contributions']}",
        "",
    ]
    return "\n".join(lines)
