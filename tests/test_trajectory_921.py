"""Every text row keeps its reasoning, finish and tokens, and the receipt says what was sent. #921."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from evals import core, environment
from evals import run as R
from evals.core import Case, Receipt, comparable
from evals.runners.repo import RepoRunner
from harness import completion, context, reasons, serving
from harness import memory_store as ms

GW = "http://gw.test"
THOUGHT = "Let me re-read workqueue.py once more. The lock is taken in claim()... " * 40
DIFF = "diff --git a/pkg/mod.py b/pkg/mod.py\n--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1 +1 @@\n-a\n+b\n"


class Attempt:
    """A checkout that grades any diff as applied and unresolved."""

    def prompt(self, text):
        return text

    def submit(self, diff):
        return SimpleNamespace(resolved=False, patch_applied=bool(diff), test_s=0.0,
                               detail="graded", failed=[], limit="", skipped=[], failures={})

    def close(self):
        pass


def _chat(content, finish, reasoning=THOUGHT, tokens=32768):
    return httpx.Response(200, json={
        "model": "m", "usage": {"prompt_tokens": 900, "completion_tokens": tokens},
        "choices": [{"finish_reason": finish, "message": {
            "role": "assistant", "content": content, "reasoning_content": reasoning}}]})


def _repo_runner(spec="fake"):
    where = serving.route(spec, GW)
    runner = RepoRunner(where.base, "fake", sampling=where.sampling or None, model=where.model,
                        template=where.template)
    runner.attempt = lambda params: Attempt()
    runner.answered = True
    return runner


CASE = Case(id="sohot-368-symptom", modality="repo", prompt="the queue stalls", params={})


def _trajectory(out: Path, case=CASE):
    return json.loads((out / core.artifact_name("fake", case.id, core.TRAJECTORY_SUFFIX)
                       ).read_text(encoding="utf-8"))


@respx.mock
def test_a_reply_cut_off_while_reasoning_leaves_its_reasoning_on_disk(tmp_path):
    respx.post(f"{GW}/v1/chat/completions").mock(return_value=_chat(None, "length"))
    row = R._one_case(_repo_runner(), CASE, None, None, (), None, None, tmp_path)
    assert row.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED
    got = _trajectory(tmp_path)
    assert got["failure_class"] == reasons.TOKEN_BUDGET_EXHAUSTED
    (one,) = got["requests"]
    assert one["reasoning"] == THOUGHT
    assert one["finish_reason"] == "length"
    assert one["completion_tokens"] == 32768 and one["prompt_tokens"] == 900
    assert one["request"]["max_tokens"] == completion.budget("repo")


@respx.mock
def test_an_answered_row_keeps_its_reasoning_beside_the_reply(tmp_path):
    respx.post(f"{GW}/v1/chat/completions").mock(return_value=_chat(DIFF, "stop", tokens=2985))
    R._one_case(_repo_runner(), CASE, None, None, (), None, None, tmp_path)
    (one,) = _trajectory(tmp_path)["requests"]
    assert one["reasoning"] == THOUGHT and one["finish_reason"] == "stop"
    assert one["completion_tokens"] == 2985


@respx.mock
def test_each_rung_of_a_ladder_keeps_its_own_trajectory(tmp_path):
    respx.post(f"{GW}/v1/chat/completions").mock(return_value=_chat(None, "length"))
    R._one_case(_repo_runner(), CASE, None, None, (32768, 65536), None, None, tmp_path)
    rungs = _trajectory(tmp_path)["requests"]
    assert [r["request"]["max_tokens"] for r in rungs] == [32768, 65536]
    assert all(r["reasoning"] == THOUGHT for r in rungs)


@respx.mock
@pytest.mark.parametrize("spec, sent", [
    ("fake,enable_thinking=false", {"enable_thinking": False}),
    ("fake,enable_thinking=true", {"enable_thinking": True}),
    ("fake", None),
])
def test_a_spec_thinking_flag_reaches_the_request(tmp_path, spec, sent):
    route = respx.post(f"{GW}/v1/chat/completions").mock(return_value=_chat(DIFF, "stop"))
    R._one_case(_repo_runner(spec), CASE, None, None, (), None, None, tmp_path)
    payload = json.loads(route.calls[0].request.content)
    assert payload.get("chat_template_kwargs") == sent
    (one,) = _trajectory(tmp_path)["requests"]
    assert one["request"]["template"] == (sent or {})


def test_the_full_vendor_sampler_parses_from_a_spec():
    got = serving.route("fake,temperature=1.0,top_p=0.95,top_k=20,min_p=0,presence_penalty=0", GW)
    assert got.sampling == {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
                            "presence_penalty": 0.0}
    assert isinstance(got.sampling["top_k"], int)
    with pytest.raises(ValueError, match="top_k"):
        serving.route("fake,top_k=2.5", GW)
    with pytest.raises(ValueError, match="enable_thinking"):
        serving.route("fake,enable_thinking=maybe", GW)


@pytest.fixture
def quiet_receipt(monkeypatch):
    for name, value in (("accelerator_id", "unified:test"), ("where_id", "test"),
                        ("swap_used_mb", 0), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {})
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: SimpleNamespace(as_dict=lambda: {}))
    monkeypatch.setattr(context, "served_ctx", lambda spec, *a, **k: None)


def _run(tmp_path, candidates):
    cases = tmp_path / "cases"
    cases.mkdir(exist_ok=True)
    (cases / "add.yaml").write_text(
        "id: add-two\nmodality: code\nprompt: write add(a, b)\n"
        "assert:\n  checks:\n    - \"add(1, 2) == 3\"\n", encoding="utf-8")
    out = tmp_path / "out"
    R._execute(argparse.Namespace(
        screen=False, repeat=1, adherence="", cases=str(cases), modality="code",
        candidates=candidates, from_winners=False, gateway=GW, out=str(out), split="all",
        max_tokens=None, budget_ladder=None))
    return json.loads((out / "results.json").read_text(encoding="utf-8"))["receipt"]


@respx.mock
def test_a_run_with_thinking_off_says_so_in_its_receipt(tmp_path, quiet_receipt):
    respx.post(f"{GW}/v1/chat/completions").mock(
        return_value=_chat("def add(a, b):\n    return a + b\n", "stop", tokens=12))
    got = _run(tmp_path, "fake,enable_thinking=false,top_k=20")
    assert got["template"]["code"] == {"enable_thinking": False}
    (sent,) = got["requests"]["fake"]
    assert sent["template"] == {"enable_thinking": False}
    assert sent["sampling"] == {"temperature": completion.DEFAULT_TEMPERATURE, "top_k": 20}
    assert sent["max_tokens"] == completion.budget("code") and sent["system_sha"]
    assert "enable_thinking" not in got["sampling"]["code"]


@respx.mock
def test_a_run_without_the_flag_does_not_claim_one(tmp_path, quiet_receipt):
    respx.post(f"{GW}/v1/chat/completions").mock(
        return_value=_chat("def add(a, b):\n    return a + b\n", "stop", tokens=12))
    got = _run(tmp_path, "fake")
    assert "code" not in got["template"]
    (sent,) = got["requests"]["fake"]
    assert sent["template"] == {}


def test_candidates_that_disagree_on_thinking_are_refused():
    with pytest.raises(SystemExit, match="enable_thinking"):
        R.effective_template("code", ["a,enable_thinking=false", "b"])


def _receipt(**kw):
    return Receipt(**{**dict(modality="repo", case_ids=("a",), repeat=1, sampling={}, gateway=GW), **kw})


def test_thinking_on_and_off_are_two_exams_and_an_old_receipt_is_not_refused():
    off, on = _receipt(template={"repo": {"enable_thinking": False}}), _receipt(template={})
    assert comparable(off, on)[0] is False
    assert comparable(off, _receipt())[0] is True
    back = Receipt.from_dict(off.as_dict())
    assert back.template == off.template


@pytest.mark.parametrize("settings", [
    {"params": {"temperature": 0.8, "top_k": 40, "top_p": 0.95, "min_p": 0.05,
                "presence_penalty": 0.0, "repeat_penalty": 1.0, "n_probs": 0}},
    {"temperature": 0.8, "top_k": 40, "top_p": 0.95, "min_p": 0.05,
     "presence_penalty": 0.0, "repeat_penalty": 1.0},
])
def test_the_servers_own_sampler_defaults_are_read_from_its_props(settings):
    asked = []

    def get(url):
        asked.append(url)
        return {"default_generation_settings": settings}
    got = context.served_sampler("llamacpp:Ornith-1.5-35B-Q4_K_M", get=get)
    assert got == {"temperature": 0.8, "top_k": 40, "top_p": 0.95, "min_p": 0.05,
                   "presence_penalty": 0.0, "repetition_penalty": 1.0}
    assert asked[0].endswith("/props?model=Ornith-1.5-35B-Q4_K_M")


def test_a_server_that_does_not_say_leaves_the_defaults_unrecorded():
    def get(url):
        raise OSError("no /props")
    assert context.served_sampler("llamacpp:x", get=get) == {}
