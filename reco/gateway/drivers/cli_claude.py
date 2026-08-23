"""Track A driver: Anthropic subscription via the Claude Code CLI.

Hardened headless invocation: safe permission mode (never bypass), an empty
tool registry (--tools ""), strict empty MCP config so this machine's MCP
servers never leak into an agent call, cwd = empty per-agent workspace so no
CLAUDE.md is inherited, prompt via stdin, single turn, JSON output.
"""
import json
from pathlib import Path

from reco.gateway.drivers.base import DriverResult, classify_failure


class ClaudeCliDriver:
    name = "cli_claude"
    provider = "anthropic"

    def __init__(self, *, model: str, workspace, backend, executable=None):
        self.model = model
        # Absolute: the CLI resolves argv paths against its own cwd (the
        # workspace itself), so a relative workspace path would double up.
        self.workspace = Path(workspace).resolve()
        self.backend = backend
        self.executable = list(executable) if executable else ["claude"]

    def command(self, static_context: str) -> list[str]:
        mcp_config = self.workspace / "mcp-empty.json"
        return [
            *self.executable,
            "-p",
            "--output-format", "json",
            "--model", self.model,
            "--max-turns", "1",
            "--permission-mode", "default",
            "--setting-sources", "",
            # Empty registry, not deny rules: advertised-but-denied tools bait
            # the model into a tool call that --max-turns 1 then kills, and
            # deny rules naming unregistered tools abort the CLI outright.
            "--tools", "",
            "--strict-mcp-config",
            "--mcp-config", str(mcp_config),
            "--append-system-prompt", static_context,
        ]

    def decide(self, static_context: str, observation: str, timeout_s: int) -> DriverResult:
        self.workspace.mkdir(parents=True, exist_ok=True)
        mcp_config = self.workspace / "mcp-empty.json"
        if not mcp_config.exists():
            mcp_config.write_text('{"mcpServers": {}}', encoding="utf-8")

        result = self.backend.run(
            self.command(static_context),
            stdin_text=observation,
            cwd=self.workspace,
            timeout_s=timeout_s,
        )
        if result.timed_out:
            return DriverResult(error="timeout", meta={"stderr": result.stderr[-500:]})
        if result.returncode != 0:
            return DriverResult(
                error=classify_failure(result.stdout, result.stderr),
                meta={"returncode": result.returncode,
                      "stdout": result.stdout[-500:],
                      "stderr": result.stderr[-500:]},
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return DriverResult(error="transient",
                                meta={"stdout": result.stdout[-500:]})
        if payload.get("is_error"):
            return DriverResult(
                error=classify_failure(str(payload.get("result", ""))),
                meta={"payload": {k: v for k, v in payload.items() if k != "result"}},
            )
        meta = {k: payload[k] for k in ("num_turns", "session_id", "duration_ms")
                if k in payload}
        return DriverResult(
            text=payload.get("result", ""),
            usage=payload.get("usage") or {},
            meta=meta,
        )
