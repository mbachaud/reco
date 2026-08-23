"""Reco command line.

  reco run --config configs/smoke.yaml --out runs/smoke1
  reco replay runs/smoke1
  reco conformance --driver cli_claude --model claude-sonnet-4-5 --out report.json
  reco validate-content slice
  reco gate-antigravity
"""
import argparse
import json
import sys
from pathlib import Path

import yaml


def main(argv=None):
    parser = argparse.ArgumentParser(prog="reco")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run a world from a YAML config")
    p_run.add_argument("--config", required=True)
    p_run.add_argument("--out", required=True)

    p_replay = sub.add_parser("replay", help="verify a run log by provider-free replay")
    p_replay.add_argument("run_dir")

    p_report = sub.add_parser("report", help="generate report.md / report.json for a run")
    p_report.add_argument("run_dir")

    p_view = sub.add_parser("viewer", help="build the self-contained HTML replay viewer")
    p_view.add_argument("run_dir")
    p_view.add_argument("--out", default=None)

    p_conf = sub.add_parser("conformance", help="run the fixture suite against a driver")
    p_conf.add_argument("--driver", required=True,
                        choices=["cli_claude", "cli_codex", "http_openai"])
    p_conf.add_argument("--model", required=True)
    p_conf.add_argument("--base-url", default=None)
    p_conf.add_argument("--api-key-env", default=None)
    p_conf.add_argument("--timeout", type=int, default=120)
    p_conf.add_argument("--limit", type=int, default=None,
                        help="run only the first N fixtures (after --offset)")
    p_conf.add_argument("--offset", type=int, default=0,
                        help="skip the first K fixtures")
    p_conf.add_argument("--out", default=None, help="write the JSON report here")
    p_conf.add_argument("--workspace", default="runs/conformance-ws")

    p_val = sub.add_parser("validate-content", help="validate a content bundle")
    p_val.add_argument("bundle")

    sub.add_parser("gate-antigravity", help="check Track A Google availability")

    args = parser.parse_args(argv)
    return COMMANDS[args.command](args)


def _cmd_run(args):
    from reco.runner.orchestrator import run

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    summary = run(config, args.out)
    print(json.dumps(summary, indent=2))
    return 0


def _cmd_replay(args):
    from reco.runner.replay import ReplayError, replay

    try:
        report = replay(args.run_dir)
    except ReplayError as exc:
        print(f"REPLAY FAILED: {exc}")
        return 1
    print(f"replay OK: {report['ticks']} ticks, "
          f"final state {report['final_state_hash'][:16]}...")
    return 0


def _cmd_report(args):
    from reco.runner.report import generate_report

    report = generate_report(args.run_dir)
    print(f"report written to {args.run_dir}/report.md")
    print(f"project complete: {report['project_complete']} "
          f"(tick {report['complete_tick']})")
    return 0


def _cmd_viewer(args):
    from reco.runner.viewer import build_viewer

    out = args.out or str(Path(args.run_dir) / "viewer.html")
    path = build_viewer(args.run_dir, out)
    print(f"viewer written to {path}")
    return 0


def _cmd_conformance(args):
    import os

    from reco.engine.content import load_content
    from reco.gateway.backend import NativeBackend
    from reco.runner.conformance import build_fixtures, run_conformance

    content = load_content("slice")
    workspace = Path(args.workspace)
    backend = NativeBackend()
    if args.driver == "cli_claude":
        from reco.gateway.drivers.cli_claude import ClaudeCliDriver
        driver = ClaudeCliDriver(model=args.model, workspace=workspace, backend=backend)
    elif args.driver == "cli_codex":
        from reco.gateway.drivers.cli_codex import CodexCliDriver
        driver = CodexCliDriver(model=args.model, workspace=workspace, backend=backend)
    else:
        from reco.gateway.drivers.http_openai import HttpOpenAIDriver
        api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
        driver = HttpOpenAIDriver(base_url=args.base_url, model=args.model,
                                  api_key=api_key)

    fixtures = build_fixtures(content)
    if args.offset:
        fixtures = fixtures[args.offset:]
    if args.limit:
        fixtures = fixtures[: args.limit]
    report = run_conformance(driver, content, fixtures=fixtures,
                             timeout_s=args.timeout, plant_decoys=workspace)
    compact = {k: v for k, v in report.items() if k != "per_fixture"}
    print(json.dumps(compact, indent=2))
    for row in report["per_fixture"]:
        print(f"  {row['name']}: parse={row['parse']} schema={row['schema']}"
              + (f" exact={row['exact']}" if "exact" in row else ""))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


def _cmd_validate(args):
    from reco.engine.content import ContentError, load_content

    try:
        content = load_content(args.bundle)
    except ContentError as exc:
        print(f"INVALID: {exc}")
        return 1
    print(f"OK: {content['name']} ({len(content['items'])} items, "
          f"{len(content['recipes'])} recipes), hash {content['content_hash'][:16]}...")
    return 0


def _cmd_gate(args):
    from reco.gateway.drivers.cli_antigravity import check_antigravity

    result = check_antigravity()
    print(json.dumps(result, indent=2))
    return 0 if result["available"] else 1


COMMANDS = {
    "run": _cmd_run,
    "replay": _cmd_replay,
    "report": _cmd_report,
    "viewer": _cmd_viewer,
    "conformance": _cmd_conformance,
    "validate-content": _cmd_validate,
    "gate-antigravity": _cmd_gate,
}


if __name__ == "__main__":
    sys.exit(main())
