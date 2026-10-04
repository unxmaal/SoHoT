"""Recorded cards must be what the inspect tier actually reads. #257."""
import importlib.util
import io
import json
from pathlib import Path

from harness import inspect as ins

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "record_fixtures", REPO / "scripts" / "record_fixtures.py")
rec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rec)


def test_a_card_is_recorded_from_the_url_inspect_reads_with_every_file(
        tmp_path, monkeypatch):
    """The recorder asked without ?blobs=true and kept 20 of 89 files, so a
    GGUF card had no sizes and no imatrix file, the two facts #298 needed."""
    seen = []
    card = {"id": "org/m", "siblings": [{"rfilename": f"m-{i}.gguf", "size": i + 1}
                                        for i in range(89)]}

    def urlopen(req, timeout=0):
        seen.append(req.full_url)
        return io.BytesIO(json.dumps(card).encode())
    monkeypatch.setattr(rec.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(rec, "FIXTURES", tmp_path)
    got = json.loads(rec.record("org/m").read_text(encoding="utf-8"))
    assert seen == [ins.MODEL_URL.format(model_id="org/m")]
    assert len(got["siblings"]) == 89
    assert all(s["size"] for s in got["siblings"])
