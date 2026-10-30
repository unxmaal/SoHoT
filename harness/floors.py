"""Pass-threshold noise floors: a known-good instrument's per-item error on clean known inputs, from stored rows (#730)."""
from __future__ import annotations

import ast
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

#: Share of clean items a known-good instrument must pass at a derived threshold, in every stratum.
FLOOR_PASS_SHARE = 0.95
#: Items a stratum needs before its quantile may set the floor.
FLOOR_MIN_ITEMS = 10
#: A session gap is scored by the observed gaps within this factor either side of it.
FLOOR_GAP_WINDOW = 1.5

#: The known-good instrument each lane's floor is measured on: an ear not trained on LibriSpeech, the served voice, the OS reader.
REFERENCE = {"stt": "whisper-large-v3-mlx", "tts": "Kokoro-82M-bf16/bm_george", "ocr": "osocr/auto"}
#: The knob each lane's floor sets.
THRESHOLDS = {"stt_max_wer": "stt", "tts_max_wer": "tts", "ocr_max_cer": "ocr"}
#: Item-length strata, as the upper bound of each but the last: an error is 1/n of an item, so short items have coarser rates.
STRATA = {"stt": (10, 17), "tts": (10, 17), "ocr": (15, 30)}
#: The run environment keys that version each lane's instrument.
VERSION_KEYS = {"stt": ("mlx-audio", "mlx-whisper"), "tts": ("mlx-audio",), "ocr": ("macos", "rapidocr")}
#: A count of four or more digits read year-style is the voice's error, kept as one by #606, not ear noise.
_YEAR_STYLE = re.compile(r"\d{4,}")
_HEARD = "; heard "
_EAR = re.compile(r",ear=([^,]*)")
#: The word the image lane's text-render case asks for, planted at these sizes for its OCR floor.
PLANT_WORD = "OPEN"
PLANT_WORD_SIZES = (16, 20, 24, 28, 32, 36, 40, 48, 56, 64)
#: Planted case ids say what they are, so the stored rows need no case file to be read as clean.
PLANT_PREFIX = {"clean": "floor-ocr-", "word": "floor-word-"}


def stratum(units: int, lane: str) -> str:
    lo = 1
    for hi in STRATA[lane]:
        if units <= hi:
            return f"{lo}-{hi}"
        lo = hi + 1
    return f"{lo}+"


def quantile(values: list[float], share: float) -> float:
    """The smallest value at or under which at least `share` of the values fall."""
    v = sorted(values)
    return v[max(0, math.ceil(share * len(v)) - 1)]


def _low(name: str) -> int:
    got = re.match(r"\d+", name)
    return int(got.group()) if got else 0


def _pooled(by: dict, min_items: int) -> list[tuple[str, list[float]]]:
    """Strata in length order, each under `min_items` pooled into its neighbour until none is or one is left."""
    out = [(n, list(by[n])) for n in sorted(by, key=_low)]
    while len(out) > 1:
        small = [i for i, (_, r) in enumerate(out) if len(r) < min_items]
        if not small:
            break
        i = min(small, key=lambda k: len(out[k][1]))
        j = i + 1 if i + 1 < len(out) else i - 1
        a, b = sorted((i, j))
        top = out[b][0]
        name = f"{_low(out[a][0])}+" if top.endswith("+") else f"{_low(out[a][0])}-{top.split('-')[1]}"
        out[a:b + 1] = [(name, out[a][1] + out[b][1])]
    return out


def floor(items: list[dict], share: float | None = None, min_items: int | None = None) -> dict:
    """{n, strata, floor}: per case its worst rerun; strata under min_items pool with a neighbour; the floor is their largest `share` quantile."""
    share = FLOOR_PASS_SHARE if share is None else share
    min_items = FLOOR_MIN_ITEMS if min_items is None else min_items
    worst: dict = {}
    for i in items:
        if i["units"]:
            worst[i["case"]] = max(worst.get(i["case"], (i["stratum"], 0.0)), (i["stratum"], i["errors"] / i["units"]),
                                   key=lambda s: s[1])
    by = defaultdict(list)
    for name, rate in worst.values():
        by[name].append(rate)
    strata, sets = {}, []
    for name, rates in _pooled(by, min_items):
        q = quantile(rates, share)
        big = len(rates) >= min_items
        strata[name] = {"n": len(rates), "zero_share": round(sum(r == 0 for r in rates) / len(rates), 3),
                        "quantile": round(q, 4), "max": round(max(rates), 4), "sets_floor": big}
        if big:
            sets.append(q)
    return {"n": sum(s["n"] for s in strata.values()), "strata": strata,
            "units": sorted({i["units"] for i in items if i["units"]}),
            "floor": round(max(sets), 4) if sets else None,
            "complete": bool(strata) and all(s["sets_floor"] for s in strata.values())}


def derived(value: float | None, values) -> float | None:
    """The smallest of `values` at or above the floor, or None when there is no floor or it is above them all."""
    if value is None:
        return None
    above = [v for v in sorted(values) if v >= value - 1e-9]
    return above[0] if above else None


def reruns(items: list[dict]) -> dict:
    """{repeated, differ}: inputs measured in more than one run, and how many of those differ in error count."""
    by = defaultdict(set)
    runs = defaultdict(set)
    for i in items:
        by[i["case"]].add(i["errors"])
        runs[i["case"]].add((i["run"], i.get("rep", 0)))
    repeated = [c for c in by if len(runs[c]) > 1]
    differ = sorted(c for c in repeated if len(by[c]) > 1)
    return {"repeated": len(repeated), "differ": len(differ), "cases": differ}


def _rows(conn, lane: str, candidate: str, ear: str = ""):
    """(case, output, metrics, detail, run) of one candidate; with `ear`, only runs it read back (no ear recorded: the default)."""
    got = conn.execute(
        "SELECT r.case_id, r.output, r.metrics, r.detail, r.run_id, ru.receipt, ru.specs, r.repeat_index FROM results r "
        "JOIN runs ru ON ru.id = r.run_id WHERE ru.lane = ? AND r.candidate = ? ORDER BY r.id", (lane, candidate))
    out = []
    for case, output, metrics, detail, run, receipt, specs, rep in got:
        if ear and run_ear(receipt, specs, candidate) != ear:
            continue
        out.append((case, output, metrics, detail, (run, rep or 0)))
    return out


def run_ear(receipt, specs, candidate: str) -> str:
    """The ear a stored tts run read `candidate` back with: its receipt's, else its spec's ear option, else the default."""
    from harness import audio
    named = (_metrics(receipt).get("instruments") or {}).get("ear")
    if named:
        return named
    got = _EAR.search(str(_metrics(specs).get(candidate) or ""))
    return audio.ear_label(got.group(1) if got else "server")


def default_ear() -> str:
    """The ear a tts candidate with no ear option reads back with."""
    from harness import audio
    return audio.ear_label()


def _metrics(raw) -> dict:
    try:
        got = json.loads(raw or "{}")
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def _heard(detail: str) -> str | None:
    """The transcript a failing speech row quoted, or None."""
    _, sep, tail = (detail or "").rpartition(_HEARD)
    if not sep:
        return None
    try:
        got = ast.literal_eval(tail.strip())
    except (ValueError, SyntaxError):
        return None
    return got if isinstance(got, str) else None


def stt_items(conn, refs: dict, instrument: str | None = None) -> list[dict]:
    """The reference ear's stored hypotheses on manifest clips, rescored against the human transcript."""
    from harness.checks import speech
    out = []
    for case, output, _, _, run in _rows(conn, "stt", instrument or REFERENCE["stt"]):
        if case not in refs or not output:
            continue
        errors, words = speech.wer_counts(refs[case], output)
        out.append({"case": case, "run": run[0], "rep": run[1], "errors": errors, "units": words,
                    "stratum": stratum(words, "stt"), "scored": speech.NORMALISER})
    return out


def normaliser(conn, run: int) -> str:
    """The WER normaliser a stored run scored its rows with: its receipt's, else version 1. #1266."""
    got = conn.execute("SELECT receipt FROM runs WHERE id = ?", (run,)).fetchone()
    return (_metrics(got[0] if got else "{}").get("instruments") or {}).get("wer", "1")


def tts_items(conn, prompts: dict, instrument: str | None = None, ear: str = "") -> list[dict]:
    """The served voice's read-backs of sentences with no 4-digit count, rescored where the row kept what was heard."""
    from harness.checks import speech
    out = []
    for case, _, metrics, detail, run in _rows(conn, "tts", instrument or REFERENCE["tts"], ear or default_ear()):
        prompt = prompts.get(case)
        if not prompt or _YEAR_STYLE.search(prompt):
            continue
        heard = _heard(detail)
        scored = speech.NORMALISER
        if heard is not None:
            errors, words = speech.wer_counts(prompt, heard)
        else:
            scored = normaliser(conn, run[0])
            m = _metrics(metrics)
            if "wer_words" not in m:
                continue
            errors, words = m["wer_errors"], m["wer_words"]
        out.append({"case": case, "run": run[0], "rep": run[1], "errors": errors, "units": words,
                    "stratum": stratum(words, "tts"), "scored": scored})
    return out


def _clean(case: str, cases: dict) -> str:
    """"word" for a planted text-render word, "clean" for an undegraded render, else ""."""
    if case.startswith(PLANT_PREFIX["word"]):
        return "word"
    if case.startswith(PLANT_PREFIX["clean"]) or (cases.get(case) or {}).get("degrade") == "none":
        return "clean"
    return ""


def ocr_items(conn, cases: dict, instrument: str | None = None, word: bool = False) -> list[dict]:
    """The OS reader on clean renders (degrade none); `word` keeps only the planted text-render word."""
    out = []
    for case, _, metrics, _, run in _rows(conn, "ocr", instrument or REFERENCE["ocr"]):
        if _clean(case, cases) != ("word" if word else "clean"):
            continue
        m = _metrics(metrics)
        if "cer_chars" not in m:
            continue
        out.append({"case": case, "run": run[0], "rep": run[1], "errors": m["cer_errors"], "units": m["cer_chars"],
                    "stratum": stratum(m["cer_chars"], "ocr")})
    return out


def versions(conn, lane: str, items: list[dict]) -> dict:
    """{key: {version: rows}} of the instrument's packages over the runs the items came from."""
    counts = Counter(i["run"] for i in items)
    out: dict = {}
    for run, n in sorted(counts.items()):
        got = conn.execute("SELECT environment FROM runs WHERE id = ?", (run,)).fetchone()
        env = _metrics(got[0] if got else "{}")
        for key in VERSION_KEYS[lane]:
            v = env.get(key) or (env.get("versions") or {}).get(key)
            if v:
                out.setdefault(key, Counter())[str(v)] += n
    return {k: dict(v) for k, v in out.items()}


def gaps(conn) -> list[float]:
    """Seconds between consecutive gateway requests of one client."""
    out, last = [], None
    for client, at in conn.execute("SELECT client, at FROM gateway_requests ORDER BY client, at"):
        if last is not None and last[0] == client:
            out.append(at - last[1])
        last = (client, at)
    return out


def session_gap(conn, values, window: float | None = None) -> dict:
    """{density, derived}: observed gaps within `window`x of each value; derived is the sparsest, the smaller on a tie."""
    window = FLOOR_GAP_WINDOW if window is None else window
    seen = gaps(conn)
    density = {v: sum(v / window <= g <= v * window for g in seen) for v in values}
    pick = min(sorted(values), key=lambda v: density[v]) if seen else None
    return {"n": len(seen), "density": density, "derived": pick}


def references() -> dict:
    """uid -> human transcript of every clip in the committed LibriSpeech manifest."""
    from evals.importers import librispeech
    return {e["uid"]: e["text"] for e in librispeech.manifest()}


def case_files(directory) -> dict:
    """case id -> the parsed case file, for every case under `directory`."""
    import yaml
    out = {}
    for p in sorted(Path(directory).rglob("*.yaml")):
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(raw, dict) and raw.get("id"):
            out[raw["id"]] = raw
    return out


def _entry(conn, knob: str, lane: str, items: list[dict], share, min_items, *, current=None, values=None) -> dict:
    from harness import knobs
    k = knobs.KNOBS[knob]
    got = floor(items, share, min_items)
    pick = derived(got["floor"], values or k.values)
    now = k.default() if current is None else current
    return {"knob": knob, "lane": lane, "instrument": REFERENCE[lane], "current": now, "floor": got["floor"],
            "derived": pick, "status": status(got, pick), "agrees": agrees(got, pick, now), "n": got["n"],
            "strata": got["strata"], "reruns": reruns(items), "versions": versions(conn, lane, items),
            "scored": dict(Counter(i["scored"] for i in items if "scored" in i))}


def status(got: dict, pick) -> str:
    """"no rows", "provisional" (a stratum is under floor_min_items), "above range", or "derived"."""
    if not got["n"]:
        return "no rows"
    if not got["complete"]:
        return "provisional"
    return "above range" if pick is None else "derived"


def same_rule(a: float, b: float, units) -> bool:
    """Whether thresholds a and b allow the same error count on every item length measured."""
    return all(math.floor(a * u + 1e-9) == math.floor(b * u + 1e-9) for u in units)


def agrees(got: dict, pick, now) -> bool:
    """Whether the knob's default stands: only a complete derivation can say it is wrong, and one allowing the same errors agrees."""
    if status(got, pick) in ("no rows", "provisional") or pick == now:
        return True
    return pick is not None and bool(got.get("units")) and same_rule(pick, now, got["units"])


def report(conn, refs: dict | None = None, prompts: dict | None = None, cases: dict | None = None,
           share: float | None = None, min_items: int | None = None) -> list[dict]:
    """One entry per threshold: its floor on the stored rows, the value derived from it, and whether the default is it."""
    from evals import core
    from evals.importers import CASES
    from harness import knobs
    refs = references() if refs is None else refs
    if prompts is None:
        prompts = {i: c.get("prompt", "") for i, c in case_files(CASES / "tts").items()}
    if cases is None:
        cases = {i: c.get("attribution") or {} for i, c in case_files(CASES / "ocr").items()}
    out = [_entry(conn, "stt_max_wer", "stt", stt_items(conn, refs), share, min_items),
           _entry(conn, "tts_max_wer", "tts", tts_items(conn, prompts), share, min_items),
           _entry(conn, "ocr_max_cer", "ocr", ocr_items(conn, cases), share, min_items)]
    word = core.load_case(CASES / "image" / "text-render.yaml").assertions["max_cer"]
    out.append({**_entry(conn, "ocr_max_cer", "ocr", ocr_items(conn, cases, word=True), share, min_items,
                         current=word), "knob": "text-render max_cer"})
    k = knobs.KNOBS["usage_session_gap"]
    gap = session_gap(conn, k.values)
    out.append({"knob": "usage_session_gap", "lane": "usage", "instrument": "gateway_requests",
                "current": k.default(), "derived": gap["derived"], "n": gap["n"], "density": gap["density"],
                "status": "derived" if gap["derived"] is not None else "no rows",
                "agrees": gap["derived"] is None or gap["derived"] == k.default()})
    return out


def plant(out, count: int | None = None) -> list[Path]:
    """Plain, undegraded renders of every ocr_synth text and of the text-render word, as ocr cases; returns the files."""
    import yaml

    from evals.importers import ocr_synth
    from harness import knobs
    out = Path(out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    rows = ocr_synth.fetch(count=count or ocr_synth.COUNT)
    plain = [(f"{PLANT_PREFIX['clean']}{r['item']:04d}", r["text"], r["size"], r["seed"] * 100003 + r["item"]) for r in rows]
    words = [(f"{PLANT_PREFIX['word']}{s}", PLANT_WORD, s, s) for s in PLANT_WORD_SIZES]
    written = []
    for case_id, text, size, seed in plain + words:
        image = f"images/{case_id}.png"
        ocr_synth.render(text, size, "plain", seed, "none").save(out / image, optimize=True)
        case = {"id": case_id, "modality": "ocr", "prompt": ocr_synth.PROMPT, "input_file": image,
                "assert": {"text": text, "max_cer": knobs.KNOBS["ocr_max_cer"].default()},
                "attribution": {"importer": "harness.floors", "transform": f"plain {size}px, undegraded",
                                "style": "plain", "size": size, "seed": seed, "degrade": "none"}}
        path = out / f"{case_id}.yaml"
        path.write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True), encoding="utf-8")
        written.append(path)
    return written


def night(planted) -> list[list[str]]:
    """The runs that measure the floors on the planted and committed known inputs, each twice: --repeat is a no-op here (#1272)."""
    from harness import runner_gaps
    kokoro = "tts:mlx-community/Kokoro-82M-bf16,voice=bm_george"
    runs = [("stt", "evals/cases/stt/librispeech", "stt:mlx-community/whisper-large-v3-mlx,backend=whisper"),
            ("stt", "evals/cases/stt/librispeech", "stt:mlx-community/parakeet-tdt-0.6b-v2"),
            ("tts", "evals/cases/tts/tts_synth", kokoro),
            ("tts", "evals/cases/tts/tts_synth", f"{kokoro},ear=whisper"),
            ("ocr", str(planted), "osocr:auto")]
    return [runner_gaps.launcher([spec], ["uv", "run", "python"], lane)
            + ["-m", "evals.run", "--split", "all", "--modality", lane, "--cases", cases, "--candidates", spec]
            for lane, cases, spec in runs for _ in range(2)]
