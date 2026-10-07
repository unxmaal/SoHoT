"""--json is on every verb, so every verb must honor it. #329."""
import ast
import json
from pathlib import Path

import pytest

from harness import cli

CLI = Path(__file__).resolve().parents[1] / "harness" / "cli.py"


def ignoring_json(source: str) -> list[str]:
    """Verbs that print to stdout without ever asking whether --json was set,
    or that send human text through note() and never emit a result."""
    bad = []
    for f in ast.parse(source).body:
        if not (isinstance(f, ast.FunctionDef) and f.name.startswith("cmd_")):
            continue
        text = ast.get_source_segment(source, f)
        calls = [n for n in ast.walk(f) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)]
        bare = [n for n in calls if n.func.id == "print"
                and not any(k.arg == "file" for k in n.keywords)]
        asks = "a.json" in text or "_JSON" in text or 'getattr(a, "json"' in text
        if bare and not asks:
            bad.append(f.name)
        names = {n.func.id for n in calls}
        if "note" in names and not names & {"emit", "say"}:
            bad.append(f.name)
    return bad


def test_the_scanner_fires_on_a_verb_that_prints_and_ignores_json():
    src = "def cmd_x(a):\n    print('hi')\n    return 0\n"
    assert ignoring_json(src) == ["cmd_x"]


def test_the_scanner_fires_on_notes_with_no_result():
    src = "def cmd_x(a):\n    note('hi')\n    return 0\n"
    assert ignoring_json(src) == ["cmd_x"]


def test_the_scanner_passes_verbs_that_honor_json():
    """Negative control: each innocent shape stays quiet."""
    src = ("def cmd_a(a):\n    if a.json:\n        print('{}')\n    else:\n"
           "        print('hi')\n"
           "def cmd_b(a):\n    note('hi')\n    emit(x=1)\n"
           "def cmd_c(a):\n    print('x', file=sys.stderr)\n"
           "def helper(a):\n    print('not a verb')\n")
    assert ignoring_json(src) == []


def test_no_verb_ignores_json():
    assert ignoring_json(CLI.read_text(encoding="utf-8")) == []


def one_object(capsys) -> dict:
    out = capsys.readouterr().out
    got = json.loads(out)
    assert out.strip().count("\n") == 0, out
    return got


def test_voices_is_one_object(capsys):
    assert cli.main(["voices", "--json"]) == 0
    got = one_object(capsys)
    assert got["ok"] and got["verb"] == "voices" and got["kokoro"]


def test_memory_ramp_is_one_object(capsys, monkeypatch):
    from harness import memory_store as ms, ramp
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", {
        "hw_model": "Mac14,12", "os": "macOS-26", "arch": "arm64",
        "fingerprint": "Mac14,12/macOS/arm64"})
    report = {"steps": [{"gb": 1.0, "level": 1, "free_pct": 90,
                         "available_gb": 10.0, "wired_gb": 1.0,
                         "swapouts": 0}],
              "stopped": "pressure warn", "last_normal_gb": 1.0,
              "margin_gb": 2.0}
    monkeypatch.setattr(ramp, "run", lambda **kw: report)
    assert cli.main(["memory", "ramp", "--json"]) == 0
    got = one_object(capsys)
    assert got["report"]["margin_gb"] == 2.0 and got["machine_id"]


def test_memory_show_is_one_object(capsys, monkeypatch):
    from harness import memory_store as ms, ramp
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", {
        "hw_model": "Mac14,12", "os": "macOS-26", "arch": "arm64",
        "fingerprint": "Mac14,12/macOS/arm64"})
    monkeypatch.setattr(ramp, "run", lambda **kw: {
        "steps": [{"gb": 1.0, "level": 1, "free_pct": 90, "available_gb": 9.0,
                   "wired_gb": 1.0, "swapouts": 0}],
        "stopped": "cap", "last_normal_gb": 1.0, "margin_gb": None})
    cli.main(["memory", "ramp"])
    capsys.readouterr()
    assert cli.main(["memory", "show", "--json"]) == 0
    assert one_object(capsys)["limits"]


def test_throughput_is_one_object(capsys, monkeypatch, tmp_path):
    from harness import throughput
    texts = tmp_path / "t.jsonl"
    texts.write_text('{"text": "a"}\n', encoding="utf-8")
    monkeypatch.setattr(throughput, "sweep", lambda *a, **kw: [
        {"concurrency": 1, "per_hour": 10.0, "p50_s": 1.0, "p95_s": 1.0,
         "errors": 0, "completion_tokens": 5, "n": 1}])
    assert cli.main(["throughput", "--model", "m", "--texts", str(texts),
                     "--json"]) == 0
    assert one_object(capsys)["levels"][0]["per_hour"] == 10.0


def test_fetch_with_nothing_queued_is_one_object(capsys):
    assert cli.main(["fetch", "--json"]) == 0
    assert one_object(capsys)["queued"] == []


@pytest.mark.parametrize("argv", [["voices"], ["fetch"]])
def test_without_json_the_human_text_stays_on_stdout(capsys, argv):
    """Negative control: the plain form is unchanged."""
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert out.strip()
    with pytest.raises(ValueError):
        json.loads(out)
