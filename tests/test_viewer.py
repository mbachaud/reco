"""Viewer pipeline: per-tick render frames exported from the provider-free
replay, embedded into a self-contained HTML player."""
import json

from reco.runner.frames import export_frames
from reco.runner.orchestrator import run
from reco.runner.viewer import build_viewer

CONFIG = {
    "seed": 42,
    "ticks": 12,
    "content": "slice",
    "agents": [
        {"id": "a1", "driver": {"type": "mock_scripted", "role": "wood"}},
        {"id": "a2", "driver": {"type": "mock_scripted", "role": "stone"}},
        {"id": "a3", "driver": {"type": "mock_scripted", "role": "meal"}},
    ],
}


class TestExportFrames:
    def test_shape_and_counts(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        data = export_frames(tmp_path / "r1")
        assert data["meta"]["width"] == 12 and data["meta"]["height"] == 12
        assert len(data["meta"]["terrain"]) == 12  # rows of terrain codes
        assert data["meta"]["names"]["a1"]
        assert data["meta"]["agents"][0]["driver"]
        summary = json.loads((tmp_path / "r1" / "summary.json").read_text(encoding="utf-8"))
        assert len(data["frames"]) == summary["ticks_committed"]
        frame = data["frames"][0]
        assert set(frame["agents"]) == {"a1", "a2", "a3"}
        assert "project" in frame and "chat" in frame and "metrics" in frame

    def test_agents_move_between_frames(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        data = export_frames(tmp_path / "r1")
        first = data["frames"][0]["agents"]["a3"]["pos"]
        later = data["frames"][-1]["agents"]["a3"]["pos"]
        assert first != later

    def test_frames_are_json_serializable(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        json.dumps(export_frames(tmp_path / "r1"))

    def test_chat_carries_display_names(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        data = export_frames(tmp_path / "r1")
        all_chat = [c for f in data["frames"] for c in f["chat"]]
        assert all_chat
        names = set(data["meta"]["names"].values())
        assert all(c["from"] in names for c in all_chat)


class TestBuildViewer:
    def test_single_file_with_embedded_data(self, tmp_path):
        run(CONFIG, tmp_path / "r1")
        out = tmp_path / "viewer.html"
        build_viewer(tmp_path / "r1", out)
        html = out.read_text(encoding="utf-8")
        assert "RECO_DATA" in html
        assert '"frames"' in html
        assert "<canvas" in html or "grid" in html
        assert "http://" not in html.split("<!--")[0] or "localhost" not in html
