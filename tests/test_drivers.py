"""Drivers: mock, OpenAI-compatible HTTP, and hardened CLI drivers (tested
against fake CLI scripts — real-CLI verification happens in conformance)."""
import http.server
import json
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from reco.gateway.backend import NativeBackend
from reco.gateway.drivers.cli_antigravity import check_antigravity
from reco.gateway.drivers.cli_claude import ClaudeCliDriver
from reco.gateway.drivers.cli_codex import CodexCliDriver
from reco.gateway.drivers.http_openai import HttpOpenAIDriver
from reco.gateway.drivers.mock import MockDriver


class TestMock:
    def test_returns_scripted_text(self):
        d = MockDriver(lambda static, obs: '[{"verb": "harvest"}]')
        r = d.decide("rules", "obs", timeout_s=5)
        assert r.error is None
        assert r.text == '[{"verb": "harvest"}]'


class _Handler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = {"choices": [{"message": {"content": '[{"verb": "harvest"}]'}}],
            "usage": {"total_tokens": 42}}

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        _Handler.last_request = json.loads(self.rfile.read(length))
        self.send_response(_Handler.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(_Handler.body).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    _Handler.status = 200
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    httpd.shutdown()


class TestHttpOpenAI:
    def test_success_path(self, server):
        d = HttpOpenAIDriver(base_url=server, model="test-model")
        r = d.decide("rules here", "obs here", timeout_s=10)
        assert r.error is None
        assert r.text == '[{"verb": "harvest"}]'
        assert r.usage.get("total_tokens") == 42
        messages = _Handler.last_request["messages"]
        assert messages[0]["role"] == "system" and "rules here" in messages[0]["content"]
        assert messages[1]["role"] == "user" and "obs here" in messages[1]["content"]

    def test_rate_limit_classified(self, server):
        _Handler.status = 429
        d = HttpOpenAIDriver(base_url=server, model="test-model")
        assert d.decide("s", "o", timeout_s=10).error == "rate_limit"

    def test_server_error_is_transient(self, server):
        _Handler.status = 503
        d = HttpOpenAIDriver(base_url=server, model="test-model")
        assert d.decide("s", "o", timeout_s=10).error == "transient"

    def test_connection_refused_is_transient(self):
        d = HttpOpenAIDriver(base_url="http://127.0.0.1:9", model="m")
        assert d.decide("s", "o", timeout_s=3).error == "transient"


def fake_cli(tmp_path, name, body):
    script = tmp_path / f"{name}.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(script)]


class TestClaudeCli:
    def test_command_is_hardened(self, tmp_path):
        d = ClaudeCliDriver(model="sonnet", workspace=tmp_path, backend=NativeBackend())
        argv = d.command("my static context")
        joined = " ".join(argv)
        assert "--output-format json" in joined
        assert "--max-turns 1" in joined
        assert "--strict-mcp-config" in joined
        assert "--setting-sources" in joined
        assert "--append-system-prompt" in joined
        assert "--dangerously-skip-permissions" not in joined

    def test_all_tools_disabled_not_denied(self, tmp_path):
        # Deny rules still ADVERTISE tools to the model: Sonnet 5 attempts a
        # (denied) tool call, the agent loop wants a second turn, and
        # --max-turns 1 kills the call with rc 1 "Reached maximum number of
        # turns" (campaign2 tick 0, all four seats). --tools "" removes the
        # registry outright so a tool call can never start. Deny rules must
        # also stay gone: CLI >= 2.1.206 aborts on rules naming unregistered
        # tools ('Permission deny rule ... matches no known tool').
        d = ClaudeCliDriver(model="sonnet", workspace=tmp_path, backend=NativeBackend())
        argv = d.command("ctx")
        assert argv[argv.index("--tools") + 1] == ""
        assert "--disallowedTools" not in argv

    def test_relative_workspace_becomes_absolute_in_argv(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        d = ClaudeCliDriver(model="sonnet", workspace=Path("runs/x/ws/a1"),
                            backend=NativeBackend())
        argv = d.command("ctx")
        mcp = argv[argv.index("--mcp-config") + 1]
        assert Path(mcp).is_absolute()

        c = CodexCliDriver(model="m", workspace=Path("runs/x/ws/a2"),
                           backend=NativeBackend())
        cargv = c.command(Path("runs/x/ws/a2/out.txt"))
        workspace_arg = cargv[cargv.index("-C") + 1]
        assert Path(workspace_arg).is_absolute()

    def test_decode_fake_cli(self, tmp_path):
        exe = fake_cli(tmp_path, "fake_claude", """
            import json, sys
            sys.stdin.read()
            print(json.dumps({"result": "[{\\"verb\\": \\"harvest\\"}]",
                              "usage": {"output_tokens": 7}, "num_turns": 1}))
        """)
        d = ClaudeCliDriver(model="sonnet", workspace=tmp_path,
                            backend=NativeBackend(), executable=exe)
        r = d.decide("rules", "obs", timeout_s=30)
        assert r.error is None
        assert r.text == '[{"verb": "harvest"}]'

    def test_rate_limit_classified(self, tmp_path):
        exe = fake_cli(tmp_path, "fake_claude_rl", """
            import sys
            sys.stdin.read()
            sys.stderr.write("Rate limit reached, please wait")
            sys.exit(1)
        """)
        d = ClaudeCliDriver(model="sonnet", workspace=tmp_path,
                            backend=NativeBackend(), executable=exe)
        assert d.decide("r", "o", timeout_s=30).error == "rate_limit"

    def test_nonzero_exit_preserves_stdout_evidence(self, tmp_path):
        # campaign2: seats failed rc=1 with empty stderr and the journal kept
        # no stdout, leaving the actual CLI error undiagnosable. The failure
        # meta must carry a stdout tail too.
        exe = fake_cli(tmp_path, "fake_claude_out", """
            import sys
            sys.stdin.read()
            sys.stdout.write("something broke in JSON mode")
            sys.exit(1)
        """)
        d = ClaudeCliDriver(model="sonnet", workspace=tmp_path,
                            backend=NativeBackend(), executable=exe)
        r = d.decide("r", "o", timeout_s=30)
        assert r.error == "transient"
        assert "something broke" in r.meta["stdout"]


class TestCodexCli:
    def test_static_context_written_to_agents_md(self, tmp_path):
        d = CodexCliDriver(model="gpt-5", workspace=tmp_path, backend=NativeBackend())
        d.prepare("the static rules")
        assert "the static rules" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    def test_decode_via_output_file(self, tmp_path):
        exe = fake_cli(tmp_path, "fake_codex", """
            import sys
            args = sys.argv[1:]
            sys.stdin.read()
            out = args[args.index("--output-last-message") + 1]
            with open(out, "w", encoding="utf-8") as f:
                f.write('[{"verb": "eat", "item": "berries"}]')
        """)
        d = CodexCliDriver(model="gpt-5", workspace=tmp_path,
                           backend=NativeBackend(), executable=exe)
        r = d.decide("rules", "obs", timeout_s=30)
        assert r.error is None
        assert r.text == '[{"verb": "eat", "item": "berries"}]'


class TestAntigravityGate:
    def test_missing_binary_fails_gate(self):
        result = check_antigravity(executable="definitely-not-a-real-binary-xyz")
        assert result["available"] is False
        assert result["reason"]
