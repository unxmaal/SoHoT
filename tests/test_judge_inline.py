"""Every artifact a judge compares is shown in the page, with no click. #461."""
import threading
import urllib.request
from http.server import HTTPServer

import pytest

from harness import human, judge_server

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="5" height="5"/></svg>'


def _receipt(text_a, text_b):
    return {"rows": [
        {"case_id": "icon#1", "candidate": "org/a", "passed": True, "artifact": text_a},
        {"case_id": "icon#1", "candidate": "local-large", "passed": True, "artifact": text_b}]}


def test_a_text_lane_artifact_resolves_to_the_file_the_runner_wrote(tmp_path):
    """svg and web rows keep the output itself in `artifact`; the file is in
    the run dir under BaseRunner.artifact's name."""
    (tmp_path / "org_a--icon#1.svg").write_text(SVG, encoding="utf-8")
    (tmp_path / "local-large--icon#1.svg").write_text(SVG, encoding="utf-8")
    p = human.pairings(_receipt(SVG, SVG), tmp_path)[0]
    assert p["a_file"].endswith(".svg") and p["b_file"].endswith(".svg")


def test_output_text_is_never_taken_for_a_path(tmp_path):
    assert human.artifact_file({"artifact": SVG, "candidate": "x", "case_id": "c"}, None) == ""


def _serve(lane, receipt, run_dir):
    judge_server.Judge.lane = lane
    judge_server.Judge.pairs = human.pairings(receipt, run_dir)
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
    srv, base = _serve(lane, _receipt(body, body), tmp_path)
    try:
        _, page = _get(base + "/")
        assert page.decode().count(tag) == 2 and "open artifact" not in page.decode()
        ctype, data = _get(base + "/file?i=0")
        assert ctype.startswith(kind) and data.decode() == body
    finally:
        srv.shutdown()


def test_raw_output_is_served_when_no_file_was_written(tmp_path):
    srv, base = _serve("svg", _receipt(SVG, SVG), tmp_path)
    try:
        _get(base + "/")
        ctype, data = _get(base + "/file?i=0")
        assert ctype.startswith("image/svg+xml") and data.decode() == SVG
    finally:
        srv.shutdown()
