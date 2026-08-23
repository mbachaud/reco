"""Build the self-contained HTML replay viewer for a run directory."""
import json
from pathlib import Path

from reco.runner.frames import export_frames

_TEMPLATE = Path(__file__).with_name("viewer_template.html")


def build_viewer(run_dir, out_path) -> Path:
    data = export_frames(run_dir)
    html = _TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__RECO_DATA__*/null", json.dumps(data, ensure_ascii=False)
    )
    out_path = Path(out_path)
    out_path.write_text(html, encoding="utf-8")
    return out_path
