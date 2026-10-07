"""Stored speech clips, read-only: the worst by WER (#94) and tts seconds per word (#91)."""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import statistics
import subprocess
import sys
from pathlib import Path

import yaml

from harness import audio, paths, runs

CASES = paths.REPO / "evals" / "cases"
MANIFEST = paths.REPO / "evals" / "importers" / "librispeech.jsonl"

_HEARD = re.compile(r"""heard (?P<quote>["'])(?P<text>.*)(?P=quote)\s*$""", re.S)


def heard(detail: str) -> str:
    """What the ear heard, from a failure detail, or "" when it does not say."""
    m = _HEARD.search(detail or "")
    return m.group("text") if m else ""


def _store_path(store) -> Path:
    from harness import memory_store as ms
    return Path(store) if store else ms.db_path()


def references(lane: str, cases_dir=None) -> dict[str, dict]:
    """case id -> {reference, audio} from the case files, then the stt manifest."""
    found: dict[str, dict] = {}
    if lane == "stt" and MANIFEST.is_file():
        from evals.importers import librispeech
        cache = librispeech.default_cache()
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                found[e["uid"]] = {"reference": librispeech.readable(e["text"]),
                                   "audio": str(cache / f"{e['uid']}.flac")}
    for f in sorted(Path(cases_dir or CASES).joinpath(lane).glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if "id" in d:
            found[str(d["id"])] = {"reference": str(d.get("prompt") or "").strip(),
                                   "audio": str(d.get("audio_file") or "")}
    return found


def _audio(raw, where: Path) -> str:
    """The recorded path, or the same file beside its receipt when it moved."""
    if not raw:
        return ""
    p = Path(raw)
    if p.is_absolute() and p.exists():
        return str(p)
    beside = where / p.name
    return str(beside) if beside.exists() else str(p)


def rows(lane: str, store=None) -> list[dict]:
    """Every stored result of a lane: the store, plus receipts under runs/ it never recorded."""
    from harness.live_audit import open_readonly
    out, known = [], set()
    root = paths.runs()
    conn = open_readonly(_store_path(store))
    try:
        for path, cand, cid, passed, art, output, met, det in conn.execute(
                "SELECT r.path, s.candidate, s.case_id, s.passed, s.artifact_path, s.output, "
                "s.metrics, s.detail FROM results s JOIN runs r ON r.id = s.run_id "
                "WHERE r.lane = ?", (lane,)):
            known.add(path)
            where = Path(path) if Path(path).is_absolute() else root / path
            out.append(_row(path, cand, cid, passed, art, output, met, det, where))
    finally:
        conn.close()
    for receipt in sorted(root.glob("**/results.json")):
        rel = str(receipt.parent.relative_to(root))
        if rel in known or str(receipt.parent) in known:
            continue
        try:
            data = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in (data.get("rows") or []) if isinstance(data, dict) else []:
            cand = str(r.get("candidate") or "")
            output, art = runs.row_fields(r, lane, receipt.parent, cand)
            if (lane == "tts" and not str(art or "").endswith(".wav")) or (
                    lane == "stt" and not output):
                continue
            out.append(_row(rel, cand, r.get("case_id", ""), r.get("passed"), art, output,
                            r.get("metrics") or {}, r.get("detail") or "", receipt.parent))
    return out


def _row(run, cand, cid, passed, art, output, met, det, where) -> dict:
    metrics = json.loads(met) if isinstance(met, str) else (met or {})
    return {"run": run, "candidate": cand, "case_id": cid.split("#")[0], "passed": bool(passed),
            "wer": metrics.get("wer"), "hypothesis": output or heard(det),
            "audio": _audio(art, where)}


def command_line(argv: list[str], platform: str = sys.platform) -> str:
    """argv as one line a person can paste into this platform's shell: cmd quoting on win32, POSIX elsewhere."""
    return subprocess.list2cmdline(argv) if platform == "win32" else shlex.join(argv)


def play(path: str) -> str:
    try:
        return command_line(audio.play_argv(path))
    except audio.AudioError:
        return command_line(["ffplay", "-autoexit", path])


def _digest(path: str) -> str:
    """The same audio copied into two receipts is one clip."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return path


def worst(lane: str, n: int = 10, store=None, cases_dir=None) -> list[dict]:
    """stt: clips ranked by median WER across candidates, which one broken
    candidate cannot move and a wrong reference does. tts: each clip by its WER."""
    refs = references(lane, cases_dir)
    scored = [r for r in rows(lane, store) if r["wer"] is not None and r["case_id"] in refs]
    picked = []
    if lane == "stt":
        groups: dict[str, list[dict]] = {}
        for r in scored:
            groups.setdefault(r["case_id"], []).append(r)
        for cid, rs in groups.items():
            rs.sort(key=lambda r: (r["wer"], r["candidate"]))
            picked.append({**rs[len(rs) // 2], "audio": refs[cid]["audio"],
                           "median_wer": statistics.median(r["wer"] for r in rs),
                           "mean_wer": statistics.fmean(r["wer"] for r in rs),
                           "max_wer": rs[-1]["wer"], "candidates": len(rs)})
        picked.sort(key=lambda c: (-c["median_wer"], -c["mean_wer"], c["case_id"]))
    else:
        seen = set()
        for r in sorted(scored, key=lambda r: (-r["wer"], r["run"], r["candidate"])):
            key = _digest(r["audio"]) if r["audio"] else ""
            if key and key not in seen:
                seen.add(key)
                picked.append({**r, "median_wer": r["wer"], "mean_wer": r["wer"],
                               "max_wer": r["wer"], "candidates": 1})
    out = []
    for c in picked:
        if c["median_wer"] <= 0 or len(out) >= n:
            continue
        out.append({**c, "reference": refs[c["case_id"]]["reference"], "play": play(c["audio"])})
    return out


def _summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    v = sorted(values)
    return {"n": len(v), "min": v[0], "median": statistics.median(v), "max": v[-1]}


def rates(store=None, cases_dir=None) -> dict:
    """Seconds of audio per word of text over stored tts clips, the quantity the runaway ceiling gates."""
    refs = references("tts", cases_dir)
    clips, seen = [], set()
    for r in rows("tts", store):
        ref = refs.get(r["case_id"])
        if not ref or not r["audio"] or _digest(r["audio"]) in seen:
            continue
        seconds = audio.audio_seconds(r["audio"])
        words = len(ref["reference"].split())
        if seconds <= 0 or not words:
            continue
        seen.add(_digest(r["audio"]))
        clips.append({**r, "seconds": seconds, "words": words, "rate": seconds / words})
    clips.sort(key=lambda c: c["rate"])
    return {"ceiling": audio.SECONDS_PER_WORD_CEILING, "clips": clips,
            "passing": _summary([c["rate"] for c in clips if c["passed"]]),
            "failing": _summary([c["rate"] for c in clips if not c["passed"]])}


def worst_text(lane: str, got: list[dict]) -> str:
    lines = []
    for i, c in enumerate(got, 1):
        wer = (f"median WER {c['median_wer']:.2f} over {c['candidates']} candidates, "
               f"mean {c['mean_wer']:.2f}, worst {c['max_wer']:.2f}"
               if lane == "stt" else f"WER {c['max_wer']:.2f}, {c['candidate']}")
        lines += [f"{i}. {c['case_id']}  {wer}",
                  f"   reference:  {c['reference']}",
                  f"   heard:      {c['hypothesis'] or '(not stored)'}",
                  f"   play:       {c['play']}"]
    return "\n".join(lines) or f"no {lane} clip with a WER above zero"


def rates_text(got: dict) -> str:
    lines = [f"{c['rate']:.3f} s/word  {c['seconds']:6.2f}s  {c['words']:3d} words  "
             f"{'pass' if c['passed'] else 'FAIL'}  {c['candidate']}  {c['case_id']}  {c['run']}"
             for c in got["clips"]]
    for k in ("passing", "failing"):
        s = got[k]
        lines.append(f"{k}: n={s['n']}" + ("" if not s["n"] else
                     f" min {s['min']:.3f} median {s['median']:.3f} max {s['max']:.3f}"))
    lines.append(f"ceiling: {got['ceiling']:.3f} s/word")
    return "\n".join(lines)
