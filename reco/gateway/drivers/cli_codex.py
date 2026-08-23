"""Track A driver: ChatGPT-plan subscription via the Codex CLI.

`codex exec` in a read-only sandbox, cwd = per-agent workspace whose AGENTS.md
carries the static context, prompt via stdin, final message read from
--output-last-message (sidesteps stdout log noise entirely).
"""
from pathlib import Path

from reco.gateway.drivers.base import DriverResult, classify_failure


class CodexCliDriver:
    name = "cli_codex"
    provider = "openai"

    def __init__(self, *, model: str, workspace, backend, executable=None):
        self.model = model
        # Absolute: codex resolves -C and --output-last-message against its
        # own cwd, so a relative workspace path would double up.
        self.workspace = Path(workspace).resolve()
        self.backend = backend
        self.executable = list(executable) if executable else ["codex"]

    def prepare(self, static_context: str) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        (self.workspace / "AGENTS.md").write_text(static_context, encoding="utf-8")

    def command(self, out_file) -> list[str]:
        return [
            *self.executable,
            "exec",
            "-m", self.model,
            "--sandbox", "read-only",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "-c", "skills.enabled=false",
            "-C", str(self.workspace),
            "--output-last-message", str(out_file),
        ]

    def decide(self, static_context: str, observation: str, timeout_s: int) -> DriverResult:
        self.prepare(static_context)
        out_file = self.workspace / "last_message.txt"
        if out_file.exists():
            out_file.unlink()

        result = self.backend.run(
            self.command(out_file),
            stdin_text=observation,
            cwd=self.workspace,
            timeout_s=timeout_s,
        )
        if result.timed_out:
            return DriverResult(error="timeout", meta={"stderr": result.stderr[-500:]})
        if not out_file.exists():
            error = (
                classify_failure(result.stdout, result.stderr)
                if result.returncode != 0
                else "transient"
            )
            return DriverResult(
                error=error,
                meta={"returncode": result.returncode, "stderr": result.stderr[-500:]},
            )
        return DriverResult(
            text=out_file.read_text(encoding="utf-8"),
            meta={"returncode": result.returncode},
        )
