"""NativeBackend: spawns CLI subprocesses with stdin prompts, UTF-8 pipes,
an environment allowlist, and hard timeout kill of the whole process tree."""
import sys
import textwrap

from reco.gateway.backend import NativeBackend


def fake_cli(tmp_path, body):
    script = tmp_path / "fake_cli.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(script)]


class TestRun:
    def test_captures_stdout_and_exit_code(self, tmp_path):
        argv = fake_cli(tmp_path, """
            import sys
            data = sys.stdin.read()
            print(f"got {len(data)} chars")
        """)
        r = NativeBackend().run(argv, stdin_text="hello there", cwd=tmp_path, timeout_s=30)
        assert r.returncode == 0
        assert "got 11 chars" in r.stdout
        assert r.timed_out is False

    def test_unicode_round_trip(self, tmp_path):
        argv = fake_cli(tmp_path, """
            import sys
            sys.stdout.write(sys.stdin.read())
        """)
        r = NativeBackend().run(argv, stdin_text="héllo — 世界", cwd=tmp_path, timeout_s=30)
        assert "héllo — 世界" in r.stdout

    def test_env_is_allowlisted(self, tmp_path):
        argv = fake_cli(tmp_path, """
            import os
            print(os.environ.get("RECO_SECRET_LEAK", "ABSENT"))
            print(os.environ.get("NO_COLOR", "MISSING_NO_COLOR"))
        """)
        import os
        os.environ["RECO_SECRET_LEAK"] = "leaked"
        try:
            r = NativeBackend().run(argv, stdin_text="", cwd=tmp_path, timeout_s=30)
        finally:
            del os.environ["RECO_SECRET_LEAK"]
        assert "ABSENT" in r.stdout
        assert "MISSING_NO_COLOR" not in r.stdout

    def test_autoupdater_disabled_in_child_env(self, tmp_path):
        # The claude CLI self-updates mid-run; an update racing concurrent
        # spawns is a prime suspect for silent rc-1 startup flakes
        # (campaign2 ticks 0-1). Child processes must never auto-update.
        argv = fake_cli(tmp_path, """
            import os
            print(os.environ.get("DISABLE_AUTOUPDATER", "unset"))
        """)
        r = NativeBackend().run(argv, stdin_text="", cwd=tmp_path, timeout_s=30)
        assert "1" in r.stdout
        assert "unset" not in r.stdout

    def test_extra_env_passed(self, tmp_path):
        argv = fake_cli(tmp_path, """
            import os
            print(os.environ.get("MY_FLAG", "none"))
        """)
        r = NativeBackend().run(argv, stdin_text="", cwd=tmp_path, timeout_s=30,
                                extra_env={"MY_FLAG": "on"})
        assert "on" in r.stdout

    def test_timeout_kills_process(self, tmp_path):
        argv = fake_cli(tmp_path, """
            import time
            time.sleep(60)
        """)
        r = NativeBackend().run(argv, stdin_text="", cwd=tmp_path, timeout_s=2)
        assert r.timed_out is True
