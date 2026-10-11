"""A generation or a scan that ends at our own cap records the limit; it is never read as a finding about the model. #700."""
import json
import wave
from pathlib import Path

import pytest
import yaml

from evals.core import Case
from evals.runners.speech import SpeechRunner
from harness import audio, completion, contamination as ct, hf_task, judge, knobs, live_audit, privacy, reasons, usage
from harness import memory_store as ms
from harness import rubric_eval as rv

WORDS = " ".join(f"w{i}" for i in range(60))


def _reply(message: dict, finish: str = "stop"):
    class R:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": message, "finish_reason": finish}]}
    return R()


# ---- contamination ----------------------------------------------------------

def test_a_probe_cut_off_while_thinking_is_an_error_with_a_limit_not_a_miss():
    sent = {}

    def post(url, json=None, headers=None, timeout=None):
        sent.update(json)
        return _reply({"content": None, "reasoning_content": "Let me think " * 300}, "length")
    conn = ms.connect()
    got = ct.probe(conn, "q3-8b", [Case("check-a", "decide", "p", context=WORDS)],
                   ask=ct.gateway_ask("http://gw:4000", post=post), at=5.0)
    assert got[0]["outcome"] == "error"
    assert f"contamination_max_tokens>{ct.MAX_TOKENS}" in got[0]["detail"]
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}


def test_a_thinking_prefix_is_stripped_before_the_overlap_is_scored():
    target = " ".join(f"w{i}" for i in range(ct.PREFIX_WORDS, 60))

    def post(url, json=None, headers=None, timeout=None):
        return _reply({"content": f"<think>the source is a list</think>\n{target}"})
    assert ct.gateway_ask("http://gw:4000", post=post)("m", "prefix") == target


def test_the_contamination_constants_are_registered_knobs():
    sites = knobs.registered()
    assert {"harness/contamination.py:MAX_TOKENS", "harness/contamination.py:HIT"} <= sites


# ---- rubric_eval -----------------------------------------------------------

RUBRIC = {"name": "durable-fact", "version": 1, "instructions": "Fact?", "label": "verdict",
          "schema": {"type": "object", "additionalProperties": False, "required": ["verdict", "why"],
                     "properties": {"verdict": {"enum": ["fact", "no-fact"]}, "why": {"type": "string"}}}}


@pytest.fixture
def evalset(tmp_path):
    (tmp_path / "rubric.yaml").write_text(yaml.safe_dump(RUBRIC), encoding="utf-8")
    (tmp_path / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in (
        {"id": "a", "text": "Set J6 to 2-3."}, {"id": "b", "text": "lol same"})), encoding="utf-8")
    rv.record_label(tmp_path, "a", "fact")
    rv.record_label(tmp_path, "b", "no-fact")
    return tmp_path


def test_a_rubric_reply_cut_mid_json_is_counted_truncated_not_a_disagreement(evalset):
    def post(url, json=None, timeout=None, headers=None):
        if json["messages"][-1]["content"] == "lol same":
            return _reply({"content": '{"verdict": "no-fact", "why": "a long expla'}, "length")
        return _reply({"content": '{"verdict": "fact", "why": ""}'})
    got = rv.run(rv.load_set(evalset), ["m"], "http://gw", post=post)["candidates"]["m"]
    assert got["truncated"] == 1
    assert (got["agree"], got["judged"]) == (1, 1) and got["agreement"] == 1.0


def test_the_rubric_request_asks_for_the_extract_reply_budget(evalset):
    body = rv.request(rv.load_set(evalset).rubric, "x", "m")
    assert body["max_tokens"] == completion.budget("extract")


# ---- privacy --------------------------------------------------------------

def test_the_github_scan_reads_every_issue_not_the_newest_300(monkeypatch, capsys):
    home = "/Us" + "ers/somebody/notes"
    issues = [{"number": n, "title": f"issue {n}", "body": home if n == 1 else ""} for n in range(700, 0, -1)]

    def gh(cmd, *args):
        limit = int(args[args.index("--limit") + 1])
        return (issues if cmd == "issue" else [])[:limit]
    monkeypatch.setattr(privacy, "_gh", gh)
    monkeypatch.setattr(privacy, "scan_paths", lambda root: [])
    rc = privacy.main(["--github"])
    out = capsys.readouterr().out
    assert rc == 1 and "issue#1" in out
    assert "scanned 700 issue(s) and 0 PR(s)" in out


# ---- usage ----------------------------------------------------------------

def _row():
    return {"alias": "sohot-code", "lane": "code", "at": 1.0, "error_class": ""}


def test_a_full_usage_queue_records_the_drops_and_the_audit_refuses_the_window():
    import threading
    gate = threading.Event()

    def slow():
        gate.wait(5)
        return ms.connect()
    w = usage.Writer(connect=slow, flush_s=0.01, maxsize=5, log=lambda m: None).start()
    for _ in range(40):
        w.put(_row())
    gate.set()
    w.close()
    conn = ms.connect()
    try:
        assert usage.dropped_since(conn, 0.0) == w.dropped >= 30
        bad = live_audit._gateway_errors(conn)
    finally:
        conn.close()
    assert any("dropped" in b for b in bad)


# ---- tts ------------------------------------------------------------------

SENTENCE = "the quick brown fox jumps over the lazy dog and runs into the woods beyond the river bank"


def test_a_tts_budget_covers_the_sentence_at_the_model_s_own_codec_rate(monkeypatch):
    monkeypatch.setattr(audio, "CODEC_HZ", {**audio.CODEC_HZ, "fake50": 50.0})
    words = len(SENTENCE.split())
    # A sentence read at the runaway ceiling still fits, at 50 tokens a second.
    assert audio.token_budget(SENTENCE, "org/fake50-tts") >= 50.0 * words * audio.SECONDS_PER_WORD_CEILING
    assert audio.token_budget(SENTENCE, "org/fake50-tts") > audio.token_budget(SENTENCE, "chatterbox")


def _wav(path: Path, seconds: float, rate: int = 16000) -> bytes:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(seconds * rate))
    return path.read_bytes()


def test_a_short_clip_that_filled_its_token_budget_names_the_limit(tmp_path, monkeypatch):
    text = "hello there"
    full = audio.token_budget(text, "chatterbox") / audio.codec_hz("chatterbox")
    body = _wav(tmp_path / "src.wav", full)
    ref = tmp_path / "ref.wav"
    _wav(ref, 1.0)

    class R:
        content = body

        def raise_for_status(self):
            return None
    monkeypatch.setattr(audio.httpx, "post", lambda *a, **k: R())
    runner = SpeechRunner("chatterbox", tmp_path, ref_audio=ref)
    with pytest.raises(audio.TokenCap):
        audio.speak(text, tmp_path / "o.wav", model="chatterbox", ref_audio=ref)
    monkeypatch.setattr(audio, "speak", lambda *a, **k: (_ for _ in ()).throw(
        audio.TokenCap(3.0, 200)))
    got = runner.run(Case("say-it", "tts", text))
    assert got.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED
    assert got.limit.startswith("tts_tokens>")


# ---- hf_task --------------------------------------------------------------

def test_an_ocr_reply_that_filled_max_new_tokens_names_the_limit(tmp_path):
    from evals.runners.process import _runtime_of
    assert hf_task.limit_hit(512, 512) == "hf_max_new_tokens>512"
    assert hf_task.limit_hit(40, 512) == ""
    out = tmp_path / "a.txt"
    Path(hf_task.runtime_path(out)).write_text(json.dumps(
        {"device": "mps", "limit": "hf_max_new_tokens>512"}), encoding="utf-8")
    assert _runtime_of(out)["limit"] == "hf_max_new_tokens>512"


def test_the_ocr_new_token_cap_is_one_registered_constant_the_cli_reads():
    import inspect
    assert inspect.signature(hf_task.read_image).parameters["max_new_tokens"].default is None
    assert "harness/hf_task.py:MAX_NEW_TOKENS" in knobs.registered()


# ---- judge ----------------------------------------------------------------

def test_a_name_past_the_first_chunk_of_a_long_thread_is_still_extracted():
    body = ("filler words here. " * 400) + "Later someone says vtracer beats potrace."
    seen = []

    def complete(prompt, **kw):
        seen.append(prompt)
        return "vtracer | beats potrace" if "vtracer" in prompt else "NONE"
    got = judge.mentions(body, complete=complete)
    assert ("vtracer", "beats potrace") in got and len(seen) > 1


# ---- review round 2 ---------------------------------------------------------

def test_a_length_capped_probe_that_reproduced_the_passage_is_still_a_hit():
    target = " ".join(f"w{i}" for i in range(ct.PREFIX_WORDS, 60))

    def post(url, json=None, headers=None, timeout=None):
        return _reply({"content": target + " and on and on" * 200}, "length")
    conn = ms.connect()
    got = ct.probe(conn, "m", [Case("check-a", "decide", "p", context=WORDS)],
                   ask=ct.gateway_ask("http://gw:4000", post=post), at=5.0)
    assert got[0]["outcome"] == "hit" and got[0]["overlap"] == 1.0


def test_a_cut_probe_records_its_limit_in_a_column_not_only_in_the_detail():
    def post(url, json=None, headers=None, timeout=None):
        return _reply({"content": "w32 w33"}, "length")
    conn = ms.connect()
    ct.probe(conn, "m", [Case("check-a", "decide", "p", context=WORDS)],
             ask=ct.gateway_ask("http://gw:4000", post=post), at=5.0)
    row = conn.execute("SELECT outcome, hit_limit FROM contamination_probes").fetchone()
    assert (row["outcome"], row["hit_limit"]) == ("error", f"contamination_max_tokens>{ct.MAX_TOKENS}")
    assert ms.probe_summary(conn)[0]["limited"] == 1


def _codec_server(tmp_path, monkeypatch, hz: float, natural_s_per_word: float | None):
    """A cloning server whose codec really runs at `hz`; None never stops speaking."""
    sent = []

    def post(url, json=None, timeout=None):
        sent.append(dict(json))
        natural = (len(json["input"].split()) * natural_s_per_word
                   if natural_s_per_word is not None else float("inf"))
        body = _wav(tmp_path / f"srv{len(sent)}.wav", min(natural, json["max_tokens"] / hz), rate=8000)

        class R:
            content = body

            def raise_for_status(self):
                return None
        return R()
    monkeypatch.setattr(audio.httpx, "post", post)
    monkeypatch.setattr(audio, "_MEASURED_HZ", {}, raising=False)
    ref = tmp_path / "ref.wav"
    _wav(ref, 1.0, rate=8000)
    return sent, ref


def test_an_unlisted_codec_is_measured_so_its_budget_fits_the_sentence(tmp_path, monkeypatch):
    sent, ref = _codec_server(tmp_path, monkeypatch, 400.0, 0.4)
    audio.speak(SENTENCE, tmp_path / "a.wav", model="org/fast-codec-tts", ref_audio=ref)
    audio.speak(SENTENCE, tmp_path / "b.wav", model="org/fast-codec-tts", ref_audio=ref)
    spoken = [s for s in sent if s["input"] == SENTENCE]
    assert len(sent) - len(spoken) == 1, "one calibration clip per model, then cached"
    words = len(SENTENCE.split())
    assert spoken[0]["max_tokens"] / 400.0 >= words * audio.SECONDS_PER_WORD_CEILING


def test_an_unlisted_codec_that_fills_its_budget_names_the_limit(tmp_path, monkeypatch):
    _, ref = _codec_server(tmp_path, monkeypatch, 400.0, None)
    with pytest.raises(audio.TokenCap):
        audio.speak("hello there", tmp_path / "o.wav", model="org/fast-codec-tts", ref_audio=ref)


def test_the_tts_cap_detector_constants_are_registered():
    assert not hasattr(audio, "DEFAULT_CODEC_HZ")
    assert {"harness/audio.py:TOKEN_CAP_FILL", "harness/audio.py:CALIBRATION_TOKENS"} <= knobs.registered()


def test_an_ocr_row_whose_child_filled_max_new_tokens_is_budget_exhausted(tmp_path):
    import dataclasses
    import sys
    from evals.core import load_cases
    from evals.runners.process import ProcessRunner
    from harness import engines
    here = Path(__file__).resolve().parents[1] / "evals" / "cases" / "ocr"
    case = next(c for c in load_cases(here) if c.id == "ocr-sign-open")
    fake = tmp_path / "fake_ocr.py"
    fake.write_text(
        "import json, sys\na = sys.argv\nout = a[a.index('--out') + 1]\n"
        "open(out, 'w', encoding='utf-8').write('OPEN 24')\n"
        f"open(out + {hf_task.RUNTIME_SUFFIX!r}, 'w').write("
        "json.dumps({'device': 'cpu', 'limit': 'hf_max_new_tokens>512'}))\n", encoding="utf-8")
    real = engines.resolve("hf-ocr:someorg/a-model")
    eng = dataclasses.replace(real, argv=lambda p, o, params: [
        sys.executable, str(fake), *real.argv(p, o, params)[1:]])
    row = ProcessRunner(eng, tmp_path / "out").run(case)
    assert not row.passed
    assert row.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED, row.detail
    assert row.limit == "hf_max_new_tokens>512"


class _Shape:
    def __init__(self, n):
        self.shape = (1, n)


def _fake_hf(monkeypatch, out_len: int):
    import sys
    import types
    torch = types.SimpleNamespace(float16="f16", float32="f32")

    class Net:
        config = types.SimpleNamespace(_attn_implementation="eager")

        def to(self, dev):
            return self

        def generate(self, **kw):
            return _Shape(out_len)

    class Proc:
        chat_template = None

        def __call__(self, images=None, return_tensors=None):
            return types.SimpleNamespace(pixel_values=types.SimpleNamespace(to=lambda *a, **k: None))

        tokenizer = types.SimpleNamespace(batch_decode=lambda out, skip_special_tokens=True: ["text"])
    tf = types.SimpleNamespace(
        AutoModelForImageTextToText=types.SimpleNamespace(from_pretrained=lambda *a, **k: Net()),
        AutoProcessor=types.SimpleNamespace(from_pretrained=lambda *a, **k: Proc()),
        AutoTokenizer=None)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", tf)


def test_an_encoder_decoder_reply_does_not_count_its_start_token_as_new(tmp_path, monkeypatch):
    from PIL import Image
    img = tmp_path / "i.png"
    Image.new("RGB", (4, 4)).save(img)
    for out_len, want in ((64, ""), (65, "hf_max_new_tokens>64")):
        _fake_hf(monkeypatch, out_len)
        runtime = {}
        hf_task.read_image("m", str(img), "p", max_new_tokens=64, device="cpu", runtime=runtime)
        assert runtime["limit"] == want, out_len


def test_the_mention_chunk_size_is_a_registered_knob():
    assert "harness/judge.py:MENTION_CHUNK_CHARS" in knobs.registered()
