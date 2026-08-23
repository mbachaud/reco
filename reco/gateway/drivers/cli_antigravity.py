"""Track A Google gate.

The Gemini CLI stopped serving individual accounts on 2026-06-18, so
subscription-backed Google participation depends on the Antigravity CLI
exposing a usable headless prompt mode. Until check_antigravity() passes on a
machine AND the invocation contract is verified there, Google models run via
Track B (Gemini API / Vertex through HttpOpenAIDriver) only.
"""
import shutil
import subprocess
import sys


def check_antigravity(executable: str = "antigravity") -> dict:
    path = shutil.which(executable)
    if path is None:
        return {
            "available": False,
            "reason": f"{executable!r} not found on PATH - the all-subscription "
                      "three-provider pilot is unavailable; Google participates "
                      "through Track B (Gemini API / Vertex)",
        }
    try:
        probe = subprocess.run(
            [path, "--help"],
            capture_output=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
    except Exception as exc:
        return {"available": False, "reason": f"probe failed: {exc!r}"}
    helptext = (probe.stdout or "") + (probe.stderr or "")
    return {
        "available": False,
        "reason": "binary found but headless prompt contract is unverified - "
                  "verify manually before enabling a driver",
        "help_excerpt": helptext[:2000],
        "path": path,
    }
