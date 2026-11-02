"""Engines and runners wanted are classified, trialed sandboxed and screened; an untestable one is filed once. #1475."""
from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import redact
from harness import delegate, morning
from harness import engine_trials as et
from harness import memory_store as ms
from harness.commands import loop

FAKE_ENGINE = "fakeorg/fast-serve"
UNTESTABLE = "fakeorg/c-only-engine"
UNRELATED = "fakeorg/awesome-list"
CANDIDATE = "fakeorg/Odd-Arch-1B"
#: The real process runner, taken before the conftest guard replaces it.
REAL_RUN = et._run

OPENAI_READING = {"kind": "engine", "why": "an OpenAI-compatible server for Apple Silicon", "interface": "openai",
                  "serve": ["fast-serve", "--model", "{model}", "--port", "{port}"], "model_types": ["oddarch"]}
UNTESTABLE_READING = {"kind": "engine", "why": "a C inference engine", "interface": "openai",
                      "serve": ["c-serve", "-m", "{model}", "--port", "{port}"], "model_types": ["oddarch"]}
UNRELATED_READING = {"kind": "unrelated", "why": "a curated list of links, not a program"}


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _tool(conn, name, times=3):
    for i in range(times):
        ms.record(conn, ms.Seen(name=name, source="github-trending", registry="github", category="tool",
                                description=name), at=1000.0 + i)
    return {"name": name, "times": times, "registry": "github"}


def _waiting(conn, name=CANDIDATE, kind="oddarch", lane="code"):
    ms.record(conn, ms.Seen(name=name, source="hf-trending", lane=lane, registry="huggingface"))
    conn.execute("UPDATE proposals SET model_type = ? WHERE name = ?", (kind, name))
    conn.commit()
    return {"name": name, "lane": lane, "why_not": f"runners wanted: model type {kind} has no runner here"}


def _asker(**readings):
    calls = []

    def ask(prompt):
        name = next(n for n in readings if f"REPOSITORY: {n.replace('_', '/')}" in prompt)
        calls.append(name)
        return {"text": "Here it is:\n" + json.dumps(readings[name]), "spec": "fake-extract-model"}
    ask.calls = calls
    return ask


EVIDENCE = {
    FAKE_ENGINE: et.Evidence(readme="fast-serve serves models over /v1/chat/completions",
                             pypi={"package": "fast-serve", "version": "1.4.2",
                                   "wheels": ["fast_serve-1.4.2-py3-none-any.whl"]}),
    UNTESTABLE: et.Evidence(readme="build with cmake"),
    UNRELATED: et.Evidence(readme="a list"),
}


def _readings():
    return _asker(**{FAKE_ENGINE.replace("/", "_"): OPENAI_READING, UNTESTABLE.replace("/", "_"): UNTESTABLE_READING,
                     UNRELATED.replace("/", "_"): UNRELATED_READING})


class FakeGh:
    """gh issue/label calls recorded; `issues` is what `gh issue list` finds."""

    def __init__(self):
        self.calls, self.issues, self.next = [], [], 9001

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[:2] == ["issue", "list"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.issues), "")
        if argv[:2] == ["issue", "create"]:
            body = argv[argv.index("--body") + 1]
            self.issues.append({"number": self.next, "body": body})
            self.next += 1
            return subprocess.CompletedProcess(argv, 0, f"https://github.com/o/r/issues/{self.next - 1}\n", "")
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    def created(self):
        return [c for c in self.calls if c[:2] == ["issue", "create"]]


def _fake_uv(log):
    """Plays uv: `uv venv` makes the venv, `uv pip install` drops the package's console script in it."""
    def run(argv, env, cwd, timeout=et.INSTALL_TIMEOUT_S):
        log.append(argv)
        if "venv" in argv and "pip" not in argv:
            Path(argv[-1], "bin").mkdir(parents=True, exist_ok=True)
        elif "pip" in argv:
            py = Path(argv[argv.index("--python") + 1])
            (py.parent / "fast-serve").write_text("#!/bin/sh\n", encoding="utf-8")
    return run


def _sweep(conn, tools, waiting, tmp_path, gh=None, screener=None, ask=None, installs=None, now=5000.0):
    installs = [] if installs is None else installs
    return et.sweep(conn, tools, waiting, ask=ask or _readings(), evidence=EVIDENCE.__getitem__,
                    installer=lambda t, root: et.install(t, root, run=_fake_uv(installs)),
                    screener=screener or (lambda t, c: et.Screened(et.FAIL, 0, 1, "fake")),
                    gh=gh or FakeGh(), root=tmp_path / "trials", now=now,
                    known=redact.Known(accounts=("operator",), hosts=("trialbox",)))


@pytest.fixture(autouse=True)
def sandbox_here(monkeypatch):
    monkeypatch.setattr(et, "can_sandbox", lambda: True)


# ---- acceptance ----------------------------------------------------------------------------

def test_a_planted_openai_engine_is_classified_installed_in_its_own_dir_screened_and_recorded(conn, tmp_path):
    tools = [_tool(conn, FAKE_ENGINE)]
    waiting = [_waiting(conn)]
    installs, seen = [], {}

    @contextlib.contextmanager
    def served(argv, port, log, env, timeout, timeout_knob):
        seen.update(argv=argv, env=env)
        yield SimpleNamespace(base=f"http://127.0.0.1:{port}")

    class Runner:
        def run(self, case):
            return SimpleNamespace(passed=True)

    def screener(t, cand):
        return et.screen(t, cand, served=served, runner=Runner(), hold=lambda kind, deadline_s: contextlib.nullcontext())

    got = _sweep(conn, tools, waiting, tmp_path, screener=screener, installs=installs)

    (t,) = et.trials(conn)
    assert (t.kind, t.state, t.channel, t.package, t.version) == ("engine", et.INSTALLED, et.PYPI, "fast-serve", "1.4.2")
    trial_dir = Path(t.dir)
    assert trial_dir.parent == tmp_path / "trials" and (trial_dir / "installed.json").is_file()
    pip = next(a for a in installs if "pip" in a)
    assert pip[0] == et.SANDBOX_EXEC and "fast-serve==1.4.2" in pip and ":all:" in pip
    assert f"TRIAL={trial_dir.resolve()}" in pip
    argv = seen["argv"]
    assert argv[0] == et.SANDBOX_EXEC and argv[argv.index("-D") + 2] == str(trial_dir / "venv" / "bin" / "fast-serve")
    assert CANDIDATE in argv and "network-outbound" in (trial_dir.resolve() / "serve.sb").read_text(encoding="utf-8")
    assert seen["env"]["HOME"].startswith(str(trial_dir.resolve())) and seen["env"]["HF_HUB_OFFLINE"] == "1"
    (s,) = et.screens(conn)
    assert (s["engine"], s["candidate"], s["lane"], s["verdict"]) == (FAKE_ENGINE, CANDIDATE, "code", et.PASS)
    assert s["total"] >= 1 and s["passed"] == s["total"]
    assert [(e, c) for e, c, _ in got.screened] == [(FAKE_ENGINE, CANDIDATE)]
    again = _sweep(conn, tools, waiting, tmp_path, screener=screener)
    assert again.classified == [] and again.screened == [] and len(et.screens(conn)) == 1


def test_an_untestable_repo_files_exactly_one_issue_and_one_brief_line_across_two_sweeps(conn, tmp_path):
    tools = [_tool(conn, UNTESTABLE)]
    waiting = [_waiting(conn)]
    gh = FakeGh()
    _sweep(conn, tools, waiting, tmp_path, gh=gh, now=5000.0)
    _sweep(conn, tools, waiting, tmp_path, gh=gh, now=9000.0)
    (made,) = gh.created()
    body = made[made.index("--body") + 1]
    assert f"{et.MARKER} {UNTESTABLE}" in body and CANDIDATE in body and "needs a build" in body
    (t,) = et.trials(conn)
    assert t.state == et.BLOCKED and t.issue == 9001
    r = {"needs": [], "engines": morning.engines(conn, 4000.0), "incidents": [], "lane": {},
         "sweep": {"loop": None}, "watchdog": [], "ci": {}, "deploy": {}, "stale": []}
    brief = [n for n in morning.needs(r) if UNTESTABLE in n]
    assert brief == [f"engine {UNTESTABLE} could not be trialed (#9001): {t.blocker}"]
    assert morning.engines(conn, 9500.0) == []


def test_an_issue_the_tracker_already_holds_is_adopted_not_filed_again(conn, tmp_path):
    tools = [_tool(conn, UNTESTABLE)]
    gh = FakeGh()
    gh.issues = [{"number": 77, "body": f"older text\n\n{et.MARKER} {UNTESTABLE}\n"}]
    _sweep(conn, tools, [], tmp_path, gh=gh)
    assert gh.created() == [] and et.trials(conn)[0].issue == 77


def test_the_stored_issue_number_alone_keeps_filing_idempotent_when_search_finds_nothing(conn, tmp_path):
    tools = [_tool(conn, UNTESTABLE)]
    gh = FakeGh()
    blind = lambda argv: subprocess.CompletedProcess(argv, 0, "[]", "") if argv[:2] == ["issue", "list"] else gh(argv)  # noqa: E731
    _sweep(conn, tools, [], tmp_path, gh=blind)
    (t,) = et.trials(conn)
    assert et.file_issue(conn, t, tools[0], [], gh=blind) == 9001
    assert len(gh.created()) == 1


def test_an_unrelated_repo_leaves_the_list_with_its_reason(conn, tmp_path):
    tools = [_tool(conn, UNRELATED), _tool(conn, FAKE_ENGINE)]
    gh = FakeGh()
    _sweep(conn, tools, [], tmp_path, gh=gh)
    out = "\n".join(et.lines(conn, tools, [], None))
    listed = [ln for ln in out.splitlines() if ln.startswith("  3x")]
    assert [UNRELATED in ln for ln in listed] == [False]
    assert f"dropped {UNRELATED}: unrelated: a curated list of links, not a program" in out
    assert gh.created() == []


def test_a_technique_repo_is_handed_to_the_technique_path(conn, tmp_path):
    tools = [_tool(conn, UNRELATED)]
    ask = _asker(**{UNRELATED.replace("/", "_"): {"kind": "technique", "why": "speculative decoding"}})
    _sweep(conn, tools, [], tmp_path, ask=ask)
    assert conn.execute("SELECT category FROM proposals WHERE name = ?", (UNRELATED,)).fetchone()[0] == "technique"
    assert et.trials(conn)[0].state == et.DROPPED


def test_the_issue_body_holds_no_host_user_or_local_path(conn, tmp_path):
    tools = [_tool(conn, FAKE_ENGINE)]
    gh = FakeGh()

    def installer(t, root):
        raise et.TrialError("install exited 1: error writing /Users/operator/localharness/engine-trials/x on trialbox")  # privacy-ok
    et.sweep(conn, tools, [], ask=_readings(), evidence=EVIDENCE.__getitem__, installer=installer, gh=gh,
             root=tmp_path, now=5000.0, known=redact.Known(accounts=("operator",), hosts=("trialbox",)))
    (made,) = gh.created()
    text = made[made.index("--title") + 1] + "\n" + made[made.index("--body") + 1]
    for leak in ("operator", "trialbox", "/Users/", "localharness/engine-trials", str(tmp_path)):
        assert leak not in text
    assert "install exited 1" in text


def test_filing_refuses_a_body_the_privacy_scan_rejects(conn, tmp_path, monkeypatch):
    from harness import privacy
    tools = [_tool(conn, UNTESTABLE)]
    gh = FakeGh()
    monkeypatch.setattr(privacy, "check_post", lambda text, root=None: [SimpleNamespace(name="home-path")])
    got = _sweep(conn, tools, [], tmp_path, gh=gh)
    assert gh.created() == [] and "privacy" in got.stopped and et.trials(conn)[0].issue is None


# ---- the pieces ----------------------------------------------------------------------------

@pytest.mark.parametrize("serve,why", [
    ([], "names no command"),
    (["/usr/local/bin/x", "{model}", "{port}"], "not an executable"),
    (["x", "--model", "{model}"], "no {model} and {port}"),
    (["x", "{model}", "{port}", "{home}"], "{home}"),
])
def test_a_serve_command_the_harness_cannot_fill_safely_is_blocked(serve, why):
    state, *_, blocker = et.plan({**OPENAI_READING, "serve": serve}, EVIDENCE[FAKE_ENGINE])
    assert state == et.BLOCKED and why in blocker


def test_a_github_release_newer_than_the_pypi_project_is_the_one_trialed():
    ev = et.Evidence(pypi={"package": "vllm-metal", "version": "0.1.0", "wheels": ["vllm_metal-0.1.0-cp312.whl"]},
                     release={"tag": "v0.32.0", "wheels": ["vllm_metal-0.32.0-cp312-cp312-macosx_15_0_arm64.whl"]})
    assert et.plan(OPENAI_READING, ev)[:4] == (et.CLASSIFIED, et.RELEASE,
                                               "vllm_metal-0.32.0-cp312-cp312-macosx_15_0_arm64.whl", "v0.32.0")
    ev.release["tag"] = "v0.0.9"
    assert et.plan(OPENAI_READING, ev)[:4] == (et.CLASSIFIED, et.PYPI, "vllm-metal", "0.1.0")


def test_an_sdist_only_release_is_blocked_rather_than_built_outside_the_sandbox():
    ev = et.Evidence(pypi={"package": "fast-serve", "version": "1.0", "wheels": []})
    state, *_, blocker = et.plan(OPENAI_READING, ev)
    assert state == et.BLOCKED and "no wheel" in blocker


def test_a_cli_engine_waits_on_the_follow_up_adapter_and_files_nothing(conn, tmp_path):
    tools = [_tool(conn, FAKE_ENGINE)]
    ask = _asker(**{FAKE_ENGINE.replace("/", "_"): {**OPENAI_READING, "interface": "cli"}})
    gh = FakeGh()
    _sweep(conn, tools, [], tmp_path, gh=gh, ask=ask)
    assert et.trials(conn)[0].state == et.DEFERRED and gh.created() == []


def test_a_host_without_sandbox_exec_defers_the_trial(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(et, "can_sandbox", lambda: False)
    _sweep(conn, [_tool(conn, FAKE_ENGINE)], [], tmp_path)
    (t,) = et.trials(conn)
    assert t.state == et.DEFERRED and et.SANDBOX_EXEC in t.blocker


def test_a_refusing_model_stops_the_run_and_records_nothing(conn, tmp_path):
    def ask(prompt):
        raise delegate.Refused("the machine is busy")
    got = _sweep(conn, [_tool(conn, FAKE_ENGINE)], [], tmp_path, ask=ask)
    assert "did not answer" in got.stopped and et.trials(conn) == []


def test_a_reading_cut_by_its_budget_defers_that_repo_and_the_run_goes_on(conn, tmp_path):
    from harness import completion, reasons

    def ask(prompt):
        if FAKE_ENGINE in prompt:
            raise completion.CompletionError("cut", failure_class=reasons.TOKEN_BUDGET_EXHAUSTED)
        return {"text": json.dumps(UNRELATED_READING)}
    got = _sweep(conn, [_tool(conn, FAKE_ENGINE), _tool(conn, UNRELATED)], [], tmp_path, ask=ask)
    states = {t.name: (t.state, t.blocker) for t in et.trials(conn)}
    assert states[FAKE_ENGINE] == (et.DEFERRED, f"the classification ran past {et.CLASSIFY_TOKENS} tokens")
    assert states[UNRELATED][0] == et.DROPPED and got.stopped == ""


def test_an_install_past_its_timeout_blocks_the_trial_with_why(tmp_path, monkeypatch):
    def run(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])
    monkeypatch.setattr(et.subprocess, "run", run)
    with pytest.raises(et.TrialError, match=f"install ran past {et.INSTALL_TIMEOUT_S:.0f}s"):
        REAL_RUN(["uv", "pip", "install", "x==1"], {}, tmp_path)


def test_no_test_reaches_a_real_channel_through_the_default_hooks(conn, tmp_path):
    with pytest.raises(RuntimeError, match="real engine-trial channel"):
        et.gather(FAKE_ENGINE, client=object())
    with pytest.raises(RuntimeError, match="real engine-trial channel"):
        et.sweep(conn, [_tool(conn, FAKE_ENGINE)], [], evidence=EVIDENCE.__getitem__, gh=FakeGh(), root=tmp_path)


def test_a_candidate_whose_type_the_trial_does_not_list_is_not_screened(conn, tmp_path):
    called = []
    _sweep(conn, [_tool(conn, FAKE_ENGINE)], [_waiting(conn, kind="othertype")], tmp_path,
           screener=lambda t, c: called.append(c) or et.Screened(et.PASS))
    assert called == [] and et.screens(conn) == []


def test_pypi_counts_only_a_project_that_links_back_to_the_repo():
    def pypi(package):
        return {"info": {"name": package, "version": "2.0", "project_urls": {"Source": "https://github.com/other/x"}},
                "releases": {"2.0": [{"packagetype": "bdist_wheel", "filename": "x-2.0-py3-none-any.whl"}]}}
    assert et.pypi_channel("fakeorg/x", pypi) == {}
    longer = lambda package: {**pypi(package), "info": {"name": package, "version": "2.0",  # noqa: E731
                                                        "home_page": "https://github.com/fakeorg/x-extra"}}
    assert et.pypi_channel("fakeorg/x", longer) == {}
    linked = lambda package: {**pypi(package), "info": {"name": package, "version": "2.0",  # noqa: E731
                                                        "home_page": "https://github.com/FakeOrg/X"}}
    assert et.pypi_channel("fakeorg/x", linked) == {"package": "x", "version": "2.0",
                                                    "wheels": ["x-2.0-py3-none-any.whl"]}


def test_a_crashed_trial_pass_is_a_failed_step_and_the_lists_still_print(conn, monkeypatch):
    tools = [_tool(conn, FAKE_ENGINE)]
    monkeypatch.setattr(et, "sweep", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    failed = []
    lines, rc = loop._engines_lines(conn, tools, [], run=True, failed=failed)
    assert rc == 1 and failed == ["engine trials"] and any(FAKE_ENGINE in ln for ln in lines)


@pytest.mark.skipif(sys.platform != "darwin" or not Path(et.SANDBOX_EXEC).is_file(), reason="sandbox-exec is macOS")
def test_the_trial_profile_denies_a_write_outside_the_trial_dir(tmp_path):
    inside, outside = tmp_path / "trial", tmp_path / "outside.txt"
    inside.mkdir()
    ok = subprocess.run(et.sandboxed(["/bin/sh", "-c", f"echo x > {inside / 'in.txt'}"], inside, serve=True))
    bad = subprocess.run(et.sandboxed(["/bin/sh", "-c", f"echo x > {outside}"], inside, serve=True),
                         capture_output=True)
    assert ok.returncode == 0 and (inside / "in.txt").is_file()
    assert bad.returncode != 0 and not outside.exists()
