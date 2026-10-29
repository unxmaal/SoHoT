"""Planted-failure eval for `soh ask`: synthesized logs of real shape, one plant each, and their clean twins. #1335."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

KINDS = ("make_check", "pytest", "ci", "queue_job")
PLANTS = ("failing_test", "traceback", "error_count")
QUESTION = ("Did anything fail? Name each failing test, each raised exception line and each count of "
            "errors exactly as the log writes it. If nothing failed, answer none.")
#: The issue's bars: plant named in 0.95 of logs with a Wilson lower bound of 0.90; clean logs answered none in 0.95.
HIT_BAR, HIT_LOWER_BAR, NONE_BAR = 0.95, 0.90, 0.95

_WORDS = ("lane", "slot", "budget", "cursor", "verdict", "ledger", "probe", "sweep", "route", "spool",
          "knob", "lease", "batch", "shard", "chunk", "reply", "window", "queue", "store", "digest",
          "gate", "trace", "stamp", "mirror", "ramp", "badge", "frame", "quota", "hinge", "parcel")
_EXC = ("KeyError", "ValueError", "RuntimeError", "AssertionError", "TypeError", "FileNotFoundError",
        "sqlite3.OperationalError", "ModuleNotFoundError")


def _name(rng: random.Random, n: int = 3) -> str:
    return "_".join(rng.choice(_WORDS) for _ in range(n))


def _test_id(rng: random.Random) -> tuple[str, str]:
    fn = f"test_{_name(rng, 4)}"
    return f"tests/test_{_name(rng, 2)}.py::{fn}", fn


def _pytest_body(rng: random.Random, lines: int) -> list[str]:
    out, done = [], 0
    for _ in range(lines):
        r = rng.random()
        if r < 0.55:
            done = min(99, done + rng.randint(0, 2))
            out.append("." * rng.randint(20, 78) + f" [{done:3d}%]")
        elif r < 0.75:
            out.append(f"{_test_id(rng)[0]} PASSED{' ' * rng.randint(1, 20)}[{done:3d}%]")
        elif r < 0.82:
            out.append(f"tests/test_error_{_name(rng, 2)}.py::test_raises_{_name(rng, 2)} PASSED [{done:3d}%]")
        elif r < 0.88:
            out.append(f"{_test_id(rng)[0]} SKIPPED (needs the mcp group) [{done:3d}%]")
        elif r < 0.92:
            out.append(f"{_test_id(rng)[0]} XFAIL (known drift on another platform) [{done:3d}%]")
        else:
            out.append(f"  harness/{_name(rng, 1)}.py:{rng.randint(10, 900)}: DeprecationWarning: "
                       f"datetime.datetime.utcnow() is deprecated")
    return out


def _header(rng: random.Random) -> list[str]:
    return ["=" * 29 + " test session starts " + "=" * 30,
            f"platform darwin -- Python 3.12.{rng.randint(3, 9)}, pytest-8.3.{rng.randint(1, 5)}, pluggy-1.5.0",
            "rootdir: /work/project", "configfile: pyproject.toml",
            "plugins: xdist-3.6.1, anyio-4.6.2, timeout-2.3.1",
            f"created: {rng.choice((4, 8, 12))}/{rng.choice((4, 8, 12))} workers",
            f"{rng.choice((4, 8, 12))} workers [{rng.randint(800, 4000)} items]", ""]


def _summary(rng: random.Random, failed: int = 0, errors: int = 0) -> str:
    parts = ([f"{failed} failed"] if failed else []) + [f"{rng.randint(800, 4000)} passed",
                                                        f"{rng.randint(1, 40)} skipped",
                                                        f"{rng.randint(1, 5)} xfailed",
                                                        f"{rng.randint(1, 60)} warnings"]
    parts += [f"{errors} errors"] if errors else []
    return "=" * 12 + f" {', '.join(parts)} in {rng.uniform(20, 400):.2f}s " + "=" * 12


def _ci(rng: random.Random, lines: list[str]) -> list[str]:
    t = rng.randint(0, 50000)
    out = []
    for line in lines:
        t += rng.randint(0, 900)
        out.append(f"2026-10-{rng.randint(10, 27):02d}T{(t // 3600000) % 24:02d}:{(t // 60000) % 60:02d}:"
                   f"{(t // 1000) % 60:02d}.{rng.randint(0, 9999999):07d}Z {line}")
    return out


def _traceback(rng: random.Random) -> tuple[list[str], str, str]:
    exc = rng.choice(_EXC)
    token = _name(rng, 3)
    msg = {"KeyError": f"KeyError: '{token}'",
           "ModuleNotFoundError": f"ModuleNotFoundError: No module named '{token}'"}.get(
        exc, f"{exc}: {token} could not be resolved")
    frames = ["Traceback (most recent call last):"]
    for _ in range(rng.randint(2, 6)):
        mod = _name(rng, 1)
        frames += [f'  File "/work/project/harness/{mod}.py", line {rng.randint(10, 999)}, in {_name(rng, 2)}',
                   f"    return {_name(rng, 1)}({_name(rng, 1)}, {_name(rng, 1)}={_name(rng, 1)})"]
    return frames + [msg], token, msg


def _plant(rng: random.Random, kind: str, plant: str) -> tuple[list[str], list[str], str, str]:
    """(lines placed in the body, lines appended at the end, expected token, what was planted)."""
    if plant == "failing_test":
        node, fn = _test_id(rng)
        body = [f"{node} FAILED [ {rng.randint(10, 90)}%]"] if kind in ("pytest", "ci") else []
        tail = ["=" * 26 + " short test summary info " + "=" * 26,
                f"FAILED {node} - assert {rng.randint(1, 9)} == {rng.randint(10, 19)}"]
        return body, tail, fn, node
    if plant == "traceback":
        frames, token, msg = _traceback(rng)
        return frames, [], token, msg
    n = rng.randint(13, 97)
    if kind == "make_check":
        lines = [f"harness/{_name(rng, 1)}.py:{rng.randint(1, 900)}:{rng.randint(1, 80)}: F401 [*] "
                 f"`{_name(rng, 1)}` imported but unused" for _ in range(3)]
        return lines + [f"Found {n} errors.", "[*] 3 fixable with the `--fix` option."], [], str(n), f"Found {n} errors."
    if kind == "queue_job":
        return [], [f"finished: {rng.randint(120, 400)} cases, {n} errors, exit 1"], str(n), f"{n} errors"
    return [], [f"##[error]{n} errors in the lint step"], str(n), f"{n} errors"


def _log(rng: random.Random, kind: str, lines: int, plant: str | None) -> tuple[str, str, str]:
    """(text, expected token or "", what was planted or "")."""
    body, tail, expect, what = _plant(rng, kind, plant) if plant else ([], [], "", "")
    if kind == "queue_job":
        start = [f"[{rng.randint(100, 999):04d}] start 2026-10-{rng.randint(10, 27):02d} "
                 f"0{rng.randint(1, 5)}:{rng.randint(10, 59)}:00 soh measure extract --cases 200"]
        filler = []
        for i in range(lines):
            r = rng.random()
            if r < 0.8:
                filler.append(f"case {i + 1:4d} {_name(rng, 2):<28} ok {rng.uniform(0.1, 0.6):.2f}s")
            elif r < 0.9:
                filler.append(f"retry {_name(rng, 1)}: HTTP 503 busy, attempt 1 of 3, waiting 2s")
            else:
                filler.append(f"pressure level 1, swap {rng.randint(0, 900)} MiB, 0 errors so far")
        end = tail or [f"finished: {lines} cases, 0 errors, exit 0"]
    else:
        filler = _pytest_body(rng, lines)
        failed = 1 if plant == "failing_test" else 0
        start = _header(rng)
        if kind == "make_check":
            lint = body if plant == "error_count" else ["All checks passed!"]
            body = [] if plant == "error_count" else body
            start = ["uv run ruff check harness tests evals scripts", *lint,
                     "uv run --group mcp pytest -n 8", *start]
        summary = _summary(rng, failed=failed)
        end = [*tail, summary]
        if kind == "make_check" and plant:
            end.append("make: *** [check] Error 1")
    at = rng.randint(0, len(filler))
    lines_out = start + filler[:at] + body + filler[at:] + end
    if kind == "ci":
        lines_out = ["##[group]Run make check", *lines_out, "##[endgroup]",
                     *(["##[error]Process completed with exit code 2."] if plant else [])]
        lines_out = _ci(rng, lines_out)
    return "\n".join(lines_out) + "\n", expect, what


def cases(n: int = 60, seed: int = 1335) -> list[dict]:
    """n logs, each kind and plant in turn, each with a planted and a clean twin built from the same filler."""
    out = []
    for i in range(n):
        kind, plant = KINDS[i % len(KINDS)], PLANTS[(i // len(KINDS)) % len(PLANTS)]
        lines = random.Random(seed * 1000 + i).choice((40, 80, 150, 300, 600, 900, 1400))
        planted, expect, what = _log(random.Random(seed * 1000 + i), kind, lines, plant)
        clean, _, _ = _log(random.Random(seed * 1000 + i), kind, lines, None)
        out.append({"id": f"{i:03d}-{kind}-{plant}", "kind": kind, "plant": plant, "expect": expect,
                    "planted": what, "text": planted, "clean": clean})
    return out


def write(out: Path, got: list[dict]) -> list[dict]:
    """Write each case's two logs under `out`; the rows without the text, with the two paths."""
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in got:
        p, q = out / f"{c['id']}.log", out / f"{c['id']}.clean.log"
        p.write_text(c["text"], encoding="utf-8")
        q.write_text(c["clean"], encoding="utf-8")
        rows.append({k: v for k, v in c.items() if k not in ("text", "clean")} | {"path": str(p), "clean_path": str(q)})
    return rows


def named(answer: str, expect: str, word: str = "error") -> bool:
    """The plant's token is in the answer: a whole number and the count's word (error) for a count, the name otherwise."""
    if expect.isdigit():
        text = answer or ""
        return word in text.lower() and re.search(rf"(?<![\d.]){expect}(?![\d.])", text) is not None
    return expect.lower() in (answer or "").lower()


def score(rows: list[dict]) -> dict:
    from harness.intervals import wilson
    planted = [r for r in rows if r.get("planted_answer") is not None]
    clean = [r for r in rows if r.get("clean_answer") is not None]
    hits = sum(1 for r in planted if r["hit"])
    nones = sum(1 for r in clean if r["clean_none"])
    hit_lo, _ = wilson(hits, len(planted))
    none_lo, _ = wilson(nones, len(clean))
    hit = hits / len(planted) if planted else 0.0
    none = nones / len(clean) if clean else 0.0
    by = {}
    for key in ("kind", "plant"):
        for r in planted:
            b = by.setdefault(f"{key}={r[key]}", {"n": 0, "hits": 0})
            b["n"] += 1
            b["hits"] += int(r["hit"])
    return {"logs": len(planted), "hits": hits, "hit_rate": round(hit, 4), "hit_lower": hit_lo,
            "clean": len(clean), "nones": nones, "none_rate": round(none, 4), "none_lower": none_lo,
            "passes": hit >= HIT_BAR and hit_lo >= HIT_LOWER_BAR and none >= NONE_BAR,
            "by": by, "errors": sum(1 for r in rows if r.get("error"))}


SETS = ("pytest", "fresh", "third")


def generated(family: str, n: int, seed: int | None) -> tuple[list[dict], str]:
    """(cases, question) of one set: this module's pytest-shaped logs, evals.ask_plants_fresh or _third."""
    if family in ("fresh", "third"):
        import importlib
        mod = importlib.import_module(f"evals.ask_plants_{family}")
        return mod.cases(n, mod.SEED if seed is None else seed), mod.QUESTION
    if family != "pytest":
        raise ValueError(f"unknown set {family!r}: one of {', '.join(SETS)}")
    return cases(n, 1335 if seed is None else seed), QUESTION


def run(out: Path, ask, n: int = 60, seed: int | None = None, progress=None, family: str = "pytest") -> dict:
    """Ask the set's question of every planted and clean log with ask(path, question); rows to out/results.jsonl."""
    from harness import ask as asking
    got, question = generated(family, n, seed)
    rows = write(out, got)
    done = []
    with open(out / "results.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            for side, path in (("planted", r["path"]), ("clean", r["clean_path"])):
                try:
                    r[f"{side}_answer"] = ask(path, question)
                except Exception as exc:  # noqa: BLE001
                    r[f"{side}_answer"], r["error"] = None, f"{side}: {exc}"
            r["hit"] = r["planted_answer"] is not None and named(r["planted_answer"], r["expect"], r.get("word") or "error")
            r["clean_none"] = r["clean_answer"] is not None and asking.is_none(r["clean_answer"])
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            done.append(r)
            if progress:
                progress(r)
    return score(done)
