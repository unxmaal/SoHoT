"""Every artifact a judge compares is shown in the page, with no click. #461."""
import threading
import urllib.request
from http.server import HTTPServer

import pytest

from harness import human, judge_server

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="5" height="5"/></svg>'


def _receipt(text_a, text_b, run_dir=None, suffix=".svg"):
    def row(cand, text):
        f = run_dir / f"{cand.replace('/', '_')}--icon#1{suffix}" if run_dir else None
        return {"case_id": "icon#1", "candidate": cand, "passed": True, "output": text,
                "artifact_path": str(f) if f and f.exists() else None}
    return {"rows": [row("org/a", text_a), row("local-large", text_b)]}


def test_a_text_lane_row_shows_the_file_its_artifact_path_names(tmp_path):
    """results.artifact_path is the file; output is the text. #463."""
    (tmp_path / "org_a--icon#1.svg").write_text(SVG, encoding="utf-8")
    (tmp_path / "local-large--icon#1.svg").write_text(SVG, encoding="utf-8")
    p = human.pairings(_receipt(SVG, SVG, tmp_path))[0]
    assert p["a_file"].endswith(".svg") and p["b_file"].endswith(".svg")
    assert p["a_text"] == SVG


def test_output_text_is_never_taken_for_a_path(tmp_path):
    """Even output that names a real file is text; only artifact_path is a file."""
    real = tmp_path / "real.svg"
    real.write_text(SVG, encoding="utf-8")
    p = human.pairings(_receipt(str(real), str(real)))[0]
    assert p["a_file"] == "" and p["a_text"] == str(real)


def test_a_file_is_not_found_by_name_when_artifact_path_is_empty(tmp_path):
    """No run-dir glob: a file the row does not name is not its artifact. #463."""
    (tmp_path / "org_a--icon#1.svg").write_text(SVG, encoding="utf-8")
    p = human.pairings(_receipt(SVG, SVG))[0]
    assert p["a_file"] == "" and p["b_file"] == ""


def _serve(lane, receipt):
    judge_server.Judge.lane = lane
    judge_server.Judge.pairs = human.pairings(receipt)
    judge_server.Judge.files = []
    srv = HTTPServer(("127.0.0.1", 0), judge_server.Judge)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.headers.get("Content-Type"), r.read()


@pytest.mark.parametrize("lane,suffix,tag,kind", [
    ("svg", ".svg", "<img", "image/svg+xml"),
    ("web", ".html", "<iframe sandbox", "text/html"),
])
def test_svg_and_web_render_inline_and_their_files_are_served(tmp_path, lane, suffix, tag, kind):
    body = SVG if lane == "svg" else "<!doctype html><p>hi</p>"
    for stem in ("org_a--icon#1", "local-large--icon#1"):
        (tmp_path / f"{stem}{suffix}").write_text(body, encoding="utf-8")
    srv, base = _serve(lane, _receipt(body, body, tmp_path, suffix))
    try:
        _, page = _get(base + "/")
        assert page.decode().count(tag) == 2 and "open artifact" not in page.decode()
        ctype, data = _get(base + "/file?i=0")
        assert ctype.startswith(kind) and data.decode() == body
    finally:
        srv.shutdown()


def test_raw_output_is_served_when_no_file_was_written(tmp_path):
    srv, base = _serve("svg", _receipt(SVG, SVG))
    try:
        _get(base + "/")
        ctype, data = _get(base + "/file?i=0")
        assert ctype.startswith("image/svg+xml") and data.decode() == SVG
    finally:
        srv.shutdown()
