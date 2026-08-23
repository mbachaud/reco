"""Execution backends for provider CLI subprocesses.

NativeBackend (v1): resolves .cmd shims via shutil.which, passes prompts via
stdin only, builds the child environment from an allowlist (nothing else
inherited), forces UTF-8 pipes, spawns with CREATE_NEW_PROCESS_GROUP |
CREATE_NO_WINDOW, and kills the whole process tree via taskkill on timeout.
Docker/WSL backends can implement the same run() contract later.
"""
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

# Environment the child is allowed to inherit. Auth/home vars are required by
# the provider CLIs to find their login state.
ENV_ALLOWLIST = [
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "PATH", "PATHEXT",
    "COMSPEC", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "HOMEDRIVE", "HOMEPATH", "USERNAME", "PROGRAMFILES", "PROGRAMDATA",
]

ENV_OVERRIDES = {
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
    "CI": "1",
    "TERM": "dumb",
    # A CLI self-updating while dozens of concurrent calls spawn it is a
    # recipe for silent startup flakes; agent calls never auto-update.
    "DISABLE_AUTOUPDATER": "1",
}


@dataclass
class ExecResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool


class NativeBackend:
    def run(self, argv, *, stdin_text: str, cwd, timeout_s: int,
            extra_env: dict | None = None) -> ExecResult:
        argv = list(argv)
        resolved = shutil.which(argv[0])
        if resolved:
            argv[0] = resolved

        env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
        env.update(ENV_OVERRIDES)
        if extra_env:
            env.update(extra_env)

        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )

        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            env=env,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        try:
            stdout, stderr = proc.communicate(input=stdin_text, timeout=timeout_s)
            return ExecResult(proc.returncode, stdout, stderr, timed_out=False)
        except subprocess.TimeoutExpired:
            self._kill_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=10)
            except Exception:
                stdout, stderr = "", ""
            return ExecResult(None, stdout or "", stderr or "", timed_out=True)

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            proc.kill()
