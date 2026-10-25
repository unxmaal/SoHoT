"""The craft lane: run books, release pins, controls and runners, against a stand-in CLI; the real apps only when installed (#1209)."""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from evals import core, craft, craft_check
from evals.runners import craft as craft_runner
from harness import completion, reasons

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases" / "craft"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "craft"
FAKE = FIXTURES / "fake_cli.py"


def case(name):
    return core.load_case(CASES / f"{name}.yaml")


SVG, CARD = "svg-pipeline", "image-card"
FIXTURE = {SVG: "vectorcraft-svg-pipeline", CARD: "figcraft-image-card"}
EMPTY = {SVG: "vectorcraft-empty", CARD: "figcraft-empty"}


def doc(name):
    return json.loads((FIXTURES / f"{name}.inspect.json").read_text(encoding="utf-8"))


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(craft, "binary", lambda app: [sys.executable, str(FAKE), app.name])
    monkeypatch.delenv("FAKE_CRAFT_VERSION", raising=False)


def exported(c, root):
    for r in c.assertions["craft"]["requirements"]:
        if "file" in r:
            p = Path(root) / r["file"]["path"]
            p.write_bytes(b"\x89PNG\r\n" if r["file"]["magic"] == "PNG" else b"<svg/>")


@pytest.mark.parametrize("name", [SVG, CARD])
def test_both_run_books_load_with_a_pin_a_reference_and_named_controls(name):
    c = case(name)
    assert c.modality == "craft" and c.params["craft_digest"]
    assert set(craft.controls(c)) >= {"reference", "empty"} and len(craft.controls(c)) >= 4
    assert c.params["max_steps"] >= len(craft.reference_steps(c))


@pytest.mark.parametrize("name", [SVG, CARD])
def test_the_checker_passes_the_reference_document_and_fails_an_empty_one(name, tmp_path):
    c = case(name)
    exported(c, tmp_path)
    good = craft.grade(c, doc(FIXTURE[name]), tmp_path, None, None)
    assert good["passed"], good["detail"]
    empty = craft.grade(c, doc(EMPTY[name]), tmp_path / "nothing", None, None)
    assert not empty["passed"] and empty["met"] == 0, empty["detail"]


def _near_miss_svg(d, control):
    nodes = {n["name"]: n for n in _walk(d["layers"])}
    if control == "wrong-label":
        nodes["Label B"]["text"] = "Transfrom"
    else:
        nodes["Box B"]["bounds"]["y"] = 112
    return d


def _near_miss_card(d, control):
    nodes = {n["name"]: n for n in _walk(d["pages"])}
    if control == "wrong-heading":
        nodes["Heading"]["characters"] = "Red fox in sand"
    else:
        nodes["Photo"]["height"] = nodes["Photo"]["absoluteBounds"]["height"] = 185
    return d


def _walk(nodes):
    for n in nodes or []:
        yield n
        yield from _walk(n.get("children"))


@pytest.mark.parametrize("name, control, plant", [
    (SVG, "wrong-label", _near_miss_svg), (SVG, "box-misaligned", _near_miss_svg),
    (CARD, "wrong-heading", _near_miss_card), (CARD, "photo-wrong-aspect", _near_miss_card)])
def test_each_planted_near_miss_fails_the_requirement_it_names(name, control, plant, tmp_path):
    c = case(name)
    exported(c, tmp_path)
    got = craft.grade(c, plant(copy.deepcopy(doc(FIXTURE[name])), control), tmp_path, None, None)
    failed = [r["id"] for r in got["requirements"] if not r["passed"]]
    assert not got["passed"] and failed == c.params["controls"][control]["fails"], failed


@pytest.mark.parametrize("name", [SVG, CARD])
def test_validate_builds_every_control_headless_and_each_comes_out_as_named(name, fake):
    report = craft.validate(case(name), craft.binary(craft.app_of(case(name))))
    assert [r["control"] for r in report][:2] == ["reference", "empty"]
    assert all(r["ok"] for r in report), report


def test_a_near_miss_failing_some_other_requirement_is_not_a_working_control(fake):
    c = case(SVG)
    c.params["controls"]["wrong-label"]["fails"] = ["box-a"]
    report = {r["control"]: r for r in craft.validate(c, craft.binary(craft.app_of(c)))}
    assert not report["wrong-label"]["ok"] and report["wrong-label"]["failed"] == ["label-b"]
    assert report["box-misaligned"]["ok"]


def test_a_changed_release_is_refused_naming_the_pinned_one(fake, monkeypatch):
    c = case(SVG)
    monkeypatch.setenv("FAKE_CRAFT_VERSION", "0.18.0")
    with pytest.raises(craft.PinError) as got:
        craft.check_pin(c, craft.binary(craft.app_of(c)))
    msg = str(got.value)
    assert "0.18.0 is installed" in msg and "v0.17.0" in msg and c.params["release"]["sha256"] in msg
    assert "vectorcraft-cli-0.17.0-macos-universal.zip" in msg


def test_a_pinned_binary_digest_is_checked_when_the_run_book_records_one(fake):
    c = case(SVG)
    argv = craft.binary(craft.app_of(c))
    c.params["release"] = {**c.params["release"], "binary_sha256": "0" * 64}
    with pytest.raises(craft.PinError, match="binary sha256"):
        craft.check_pin(c, argv)
    c.params["release"]["binary_sha256"] = craft.file_sha256(Path(argv[0]))
    assert craft.check_pin(c, argv)["version"] == "0.17.0"


def test_a_mismatched_release_makes_an_environment_row_before_any_model_call(fake, monkeypatch):
    monkeypatch.setenv("FAKE_CRAFT_VERSION", "0.18.0")
    row = craft_runner.ReplayRunner().run(case(SVG))
    assert not row.passed and row.failure_class == reasons.ENVIRONMENT_ERROR and "pinned to" in row.detail


def test_an_absent_app_names_the_release_asset_to_install(monkeypatch):
    monkeypatch.setattr(craft, "binary", lambda app: None)
    row = craft_runner.ReplayRunner().run(case(CARD))
    assert row.failure_class == reasons.ENVIRONMENT_ERROR and "figcraft-cli-0.11.2-macos-universal.zip" in row.detail


@pytest.mark.parametrize("name", [SVG, CARD])
def test_the_reference_replay_row_scores_one(name, fake):
    row = craft_runner.ReplayRunner().run(case(name))
    assert row.passed, row.detail
    assert row.metrics["craft_requirement_rate"] == 1.0 and row.metrics["craft_render_difference"] == 0.0


def _calls(steps):
    return [{"id": f"c{i}", "type": "function", "function": {"name": "run_command", "arguments": json.dumps(s)}}
            for i, s in enumerate(steps)]


def scripted(turns):
    """A chat() that answers each step with the next scripted message."""
    sent = []

    def chat(messages, **kw):
        sent.append({"messages": copy.deepcopy(messages), "tools": kw.get("tools")})
        message = turns.pop(0) if turns else {"content": "done"}
        return completion.Completion(text=message.get("content") or "", message=message, finish="stop",
                                     usage={"prompt_tokens": 10, "completion_tokens": 5})
    chat.sent = sent
    return chat


def runner(chat):
    return craft_runner.CraftRunner("http://gateway.invalid", "fake", chat=chat, max_tokens=100)


@pytest.mark.parametrize("name", [SVG, CARD])
def test_a_model_that_builds_the_reference_through_the_server_passes(name, fake):
    c = case(name)
    chat = scripted([{"content": "", "tool_calls": _calls(craft.reference_steps(c))}, {"content": "built"}])
    row = runner(chat).run(c)
    assert row.passed, row.detail
    assert row.metrics["craft_requirement_rate"] == 1.0 and row.metrics["agent_valid_calls"] == len(
        craft.reference_steps(c))
    assert [t["function"]["name"] for t in chat.sent[0]["tools"]] == ["run_command", "list_commands"]
    assert "The working folder is" in chat.sent[0]["messages"][1]["content"]


def test_a_near_miss_build_fails_its_requirement_and_its_render_drifts_from_the_reference(fake):
    c = case(SVG)
    steps = copy.deepcopy(craft.reference_steps(c))
    steps[2]["params"]["y"] = 112
    row = runner(scripted([{"content": "", "tool_calls": _calls(steps)}, {"content": "built"}])).run(c)
    failed = [r["id"] for r in json.loads(row.output)["grade"]["requirements"] if not r["passed"]]
    assert not row.passed and failed == ["tops-aligned"]
    assert row.metrics["craft_render_difference"] > 0
    good = runner(scripted([{"content": "", "tool_calls": _calls(craft.reference_steps(c))}])).run(c)
    assert good.metrics["craft_render_difference"] == 0.0


def test_a_model_that_does_nothing_fails_every_requirement_by_name(fake):
    c = case(SVG)
    row = runner(scripted([{"content": "I cannot."}])).run(c)
    record = json.loads(row.output)
    assert not row.passed and row.failure_class == reasons.CONTENT_FAILED
    assert row.metrics["craft_requirements_met"] == 0
    assert [r["id"] for r in record["grade"]["requirements"]] == [
        r["id"] for r in c.assertions["craft"]["requirements"]]


def test_invalid_calls_are_counted_and_answered_not_raised(fake):
    c = case(SVG)
    bad = [{"id": "x1", "type": "function", "function": {"name": "no_such_tool", "arguments": "{}"}},
           {"id": "x2", "type": "function", "function": {"name": "run_command", "arguments": "{not json"}},
           {"id": "x3", "type": "function", "function": {"name": "run_command", "arguments": '{"params": {}}'}},
           {"id": "x4", "type": "function", "function": {"name": "run_command",
                                                          "arguments": '{"command": "boom"}'}}]
    chat = scripted([{"content": "", "tool_calls": bad}, {"content": "gave up"}])
    row = runner(chat).run(c)
    calls = json.loads(row.output)["steps"][0]["calls"]
    assert row.metrics["craft_invalid_calls"] == 4 and row.metrics["agent_valid_calls"] == 1
    assert [c["why"][:20] for c in calls][0].startswith("unknown tool")
    replies = [m["content"] for m in chat.sent[1]["messages"] if m["role"] == "tool"]
    assert all(r.startswith("error") for r in replies)


def test_the_tool_call_cap_stops_the_case_on_its_knob(fake, monkeypatch):
    got = []
    monkeypatch.setattr(craft, "MAX_TOOL_CALLS", 3)
    monkeypatch.setattr(craft.cuts, "cut", lambda knob, what, **kw: got.append((knob, kw)))
    c = case(SVG)
    chat = scripted([{"content": "", "tool_calls": _calls(craft.reference_steps(c))}])
    row = runner(chat).run(c)
    assert not row.passed and row.failure_class == reasons.STEP_CAP and row.limit == "craft_max_tool_calls>3"
    assert ("craft_max_tool_calls", {"value": 3, "kept": 3, "dropped": 1}) in got


def test_the_step_cap_is_the_run_books_max_steps_scaled_by_its_knob(fake, monkeypatch):
    monkeypatch.setattr(craft_runner, "MAX_STEPS_SCALE", 0.125)
    c = case(CARD)
    one = {"content": "", "tool_calls": _calls(craft.reference_steps(c)[:1])}
    chat = scripted([copy.deepcopy(one) for _ in range(5)])
    row = runner(chat).run(c)
    assert row.failure_class == reasons.STEP_CAP and row.limit == "craft_steps_scale>0.125"
    assert row.metrics["agent_steps"] == craft_runner.step_cap(c) == 2


@pytest.mark.parametrize("bad, why", [
    ({"release": {"version": "0.17.0", "tag": "v0.17.0", "asset": "x.zip", "sha256": "nothex"}}, "sha256"),
    ({"reference": "runbooks/missing.json"}, "reference"),
    ({"controls": {"x": {"step": 99, "set": {"y": 1}, "fails": ["tops-aligned"]}}}, "names no step"),
    ({"controls": {"x": {"step": 2, "set": {"colour": 1}, "fails": ["tops-aligned"]}}}, "must change"),
    ({"controls": {"x": {"step": 2, "set": {"y": 1}, "fails": ["no-such"]}}}, "requirements it fails"),
    ({"app": "photocraft"}, "params.app"),
])
def test_a_run_book_the_runner_could_not_pin_build_or_grade_is_refused_at_load(bad, why, tmp_path):
    c = case(SVG)
    shutil.copytree(CASES / "runbooks", tmp_path / "runbooks")
    params = {k: v for k, v in c.params.items() if k != "craft_digest"}
    with pytest.raises(ValueError, match=why):
        craft.validate_case(tmp_path / "x.yaml", {**params, **bad}, c.assertions)


def test_the_app_server_is_confined_to_the_working_folder():
    for app in craft.APPS.values():
        args = app.server_args(Path("work"))
        assert args[0] == "mcp" and args.count("work") == 2
        assert "--automation-read-root" in args and "--automation-write-root" in args


def test_figcraft_renders_without_system_fonts():
    assert dict(craft.APPS["figcraft"].env)["FIGCRAFT_NO_SYSTEM_FONTS"] == "1"


def test_the_craft_knobs_are_registered_with_units():
    from harness import knobs
    for name in ("craft_call_timeout", "craft_max_tool_calls", "craft_output_cap", "craft_render_difference",
                 "craft_steps_scale", "craft_geometry_tolerance"):
        k = knobs.KNOBS[name]
        assert k.unit and k.lanes == ("craft",) and k.default() in k.values and "#1209" in k.note


def test_soh_craft_validate_reports_each_control_and_records_the_documents(fake, tmp_path, capsys):
    from harness import cli
    assert cli.main(["craft", "validate", "--record", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "ok   craft-svg-pipeline box-misaligned: wants fail on tops-aligned" in out and "BAD" not in out
    assert (tmp_path / "craft-image-card.reference.inspect.json").is_file()


def test_soh_craft_validate_refuses_a_changed_release_and_revalidate_prints_the_new_pin(fake, monkeypatch, capsys):
    from harness import cli
    monkeypatch.setenv("FAKE_CRAFT_VERSION", "0.18.0")
    assert cli.main(["craft", "validate", "--case", "craft-svg-pipeline"]) == 1
    assert "pinned to vectorcraft v0.17.0" in capsys.readouterr().out
    assert cli.main(["craft", "validate", "--case", "craft-svg-pipeline", "--revalidate"]) == 0
    assert '"version": "0.18.0", "binary_sha256"' in capsys.readouterr().out


def test_evals_run_records_the_reference_row_with_its_requirements_and_knobs(fake, tmp_path, monkeypatch):
    from evals import run
    monkeypatch.setattr(run.env, "guard", lambda: None)
    shutil.copytree(CASES, tmp_path / "cases" / "craft")
    run.main(["--modality", "craft", "--candidates", craft_runner.REFERENCE, "--cases", str(tmp_path / "cases"),
              "--out", str(tmp_path / "out")])
    got = json.loads(next((tmp_path / "out").rglob("results.json")).read_text(encoding="utf-8"))
    rows = got["rows"]
    assert {r["case_id"] for r in rows} == {"craft-svg-pipeline", "craft-image-card"}
    assert all(r["passed"] and r["metrics"]["craft_requirement_rate"] == 1.0 for r in rows)
    assert got["receipt"]["knobs"]["craft_max_tool_calls"] == craft.MAX_TOOL_CALLS


def test_modality_all_leaves_the_craft_lane_out():
    from evals import run
    picked = run.select_cases([case(SVG), *core.load_cases(ROOT / "evals" / "cases" / "svg")], "all")
    assert picked and all(c.modality != "craft" for c in picked)


def test_a_non_text_candidate_is_refused_on_the_craft_lane():
    from evals import run
    with pytest.raises(SystemExit, match="cannot drive a craft app"):
        run.build_runner("claude-code:claude-opus-5-5", "", None, modality="craft")


def _real(app):
    argv = craft.binary(craft.APPS[app])
    return argv if argv and Path(argv[0]).name == craft.APPS[app].cli else None


@pytest.mark.real_runtime
@pytest.mark.parametrize("name, app", [(SVG, "vectorcraft"), (CARD, "figcraft")])
def test_the_installed_release_reproduces_each_run_books_controls(name, app):
    argv = _real(app)
    if argv is None:
        pytest.skip(f"{craft.APPS[app].cli} is not installed")
    c = case(name)
    craft.check_pin(c, argv)
    assert all(r["ok"] for r in craft.validate(c, argv))


def test_render_difference_of_a_missing_render_is_not_reported(tmp_path):
    c = case(SVG)
    got = craft.grade(c, doc(EMPTY[SVG]), tmp_path, tmp_path / "none.png", tmp_path / "none.png")
    assert got["render_difference"] is None and not got["render_ok"]
    assert craft_check.MAGIC_SPAN >= len("<svg")
    assert os.path.isdir(tmp_path)
