"""A second planted-failure set for `soh ask`: go, jest, cargo, lint and gradle logs with their own plant wording. #1335."""
from __future__ import annotations

import random

from evals.ask_plants import PLANTS

KINDS = ("go", "jest", "cargo", "lint", "gradle")
QUESTION = ("What went wrong in this run? List every failing test, crash and error count, quoted from the log. "
            "Answer none if it all passed.")
SEED = 2026

_WORDS = ("amber", "basin", "cobalt", "delta", "ember", "fjord", "garnet", "harbor", "indigo", "juniper",
          "kestrel", "lantern", "meadow", "nimbus", "orchid", "pylon", "quartz", "rivet", "summit", "tundra",
          "umber", "vertex", "willow", "yarrow", "zephyr", "anvil", "bramble", "cinder", "dune", "estuary")


def _w(rng: random.Random, n: int = 2, sep: str = "_") -> str:
    return sep.join(rng.choice(_WORDS) for _ in range(n))


def _camel(rng: random.Random, n: int = 2) -> str:
    return "".join(rng.choice(_WORDS).capitalize() for _ in range(n))


def _noise(rng: random.Random) -> str:
    return rng.choice((f"WARN retrying fetch of {_w(rng)}.tar.gz (attempt 2 of 5): connection reset by peer",
                       f"INFO cache hit for key {_w(rng, 3, '-')}-{rng.randint(1000, 9999)}",
                       f"level=info msg=\"recovered after transient error\" component={_w(rng, 1)}",
                       f"Downloading {_w(rng, 1)}-{rng.randint(1, 9)}.{rng.randint(0, 20)}.0 ({rng.randint(10, 900)} kB)"))


def _filler(rng: random.Random, kind: str, n: int) -> list[str]:
    out = []
    for _ in range(n):
        r = rng.random()
        if r < 0.1:
            out.append(_noise(rng))
            continue
        name = _camel(rng)
        if kind == "go":
            out += [f"=== RUN   Test{name}"] + ([f"--- PASS: Test{name} ({rng.uniform(0, 2):.2f}s)"] if r < 0.85 else
                                                [f"--- SKIP: Test{name} (0.00s)", f"    {name.lower()}_test.go:{rng.randint(5, 200)}: needs docker"])
            if rng.random() < 0.1:
                out.append(f"ok  \texample.com/proj/{_w(rng, 1)}\t{rng.uniform(0, 3):.3f}s")
        elif kind == "jest":
            out.append(f"  ✓ {_w(rng, 3, ' ')} ({rng.randint(1, 90)} ms)" if r < 0.8 else
                       f"  ○ skipped {_w(rng, 2, ' ')}" if r < 0.9 else
                       f"PASS src/{_w(rng, 1)}/{_w(rng, 1)}.test.ts ({rng.uniform(0, 5):.3f} s)")
        elif kind == "cargo":
            out.append(f"test {_w(rng, 1)}::tests::{_w(rng)} ... ok" if r < 0.8 else
                       f"test {_w(rng, 1)}::tests::{_w(rng)} ... ignored" if r < 0.9 else
                       f"warning: unused variable: `{_w(rng, 1)}`")
        elif kind == "lint":
            out.append(f"src/{_w(rng, 1)}/{_w(rng, 1)}.py:{rng.randint(1, 400)}: note: By default the bodies of "
                       f"untyped functions are not checked" if r < 0.4 else
                       f"  {rng.randint(1, 300)}:{rng.randint(1, 80)}  warning  '{_w(rng, 1)}' is assigned a value "
                       f"but never used  no-unused-vars" if r < 0.8 else
                       f"Checking src/{_w(rng, 1)}/{_w(rng, 1)}.ts")
        else:
            out.append(f"{name}Test > {_w(rng, 1)}{_camel(rng, 1)}() PASSED" if r < 0.8 else
                       f"{name}Test > {_w(rng, 1)}{_camel(rng, 1)}() SKIPPED" if r < 0.9 else
                       f"> Task :{_w(rng, 1)}:compileJava UP-TO-DATE")
    return out[:n]


def _plant(rng: random.Random, kind: str, plant: str) -> tuple[list[str], list[str], str, str, str]:
    """(body lines, tail lines, expected token, what was planted, the count's word)."""
    token, camel = _w(rng, 3), _camel(rng, 2)
    n = rng.randint(2, 64)
    if kind == "go":
        if plant == "failing_test":
            return ([f"=== RUN   Test{camel}", f"    {camel.lower()}_test.go:{rng.randint(5, 300)}: got {n}, want {n + 1}",
                     f"--- FAIL: Test{camel} ({rng.uniform(0, 2):.2f}s)"],
                    ["FAIL", f"FAIL\texample.com/proj/{_w(rng, 1)}\t{rng.uniform(0, 3):.3f}s"], f"Test{camel}",
                    f"--- FAIL: Test{camel}", "")
        if plant == "traceback":
            return ([f"panic: ledger: shard \"{token}\" already closed", "", f"goroutine {rng.randint(1, 90)} [running]:",
                     f"example.com/proj/ledger.(*Shard).Flush(0x0)", f"\t/work/proj/ledger/shard.go:{rng.randint(10, 300)} +0x1c"],
                    [f"FAIL\texample.com/proj/ledger\t{rng.uniform(0, 3):.3f}s"], token, f"panic: ledger: shard \"{token}\"", "")
        return ([], [f"DONE {rng.randint(200, 900)} tests, {n} failures in {rng.uniform(5, 90):.1f}s"], str(n),
                f"{n} failures", "fail")
    if kind == "jest":
        title = _w(rng, 3, " ")
        if plant == "failing_test":
            return ([f"FAIL src/{_w(rng, 1)}.test.ts", f"  ● {camel} › {title}", "",
                     "    expect(received).toBe(expected) // Object.is equality", f"    Expected: {n + 1}", f"    Received: {n}"],
                    [f"Tests:       1 failed, {rng.randint(50, 400)} passed, {rng.randint(400, 500)} total"], title, title, "")
        if plant == "traceback":
            return ([f"TypeError: Cannot read properties of undefined (reading '{token}')",
                     f"    at Ledger.flush (src/ledger.ts:{rng.randint(10, 300)}:{rng.randint(1, 40)})",
                     f"    at processTicksAndRejections (node:internal/process/task_queues:95:5)"],
                    [], token, f"TypeError: ... (reading '{token}')", "")
        return ([], [f"Test Suites: {n} failed, {rng.randint(10, 60)} passed, {rng.randint(70, 90)} total"], str(n),
                f"Test Suites: {n} failed", "fail")
    if kind == "cargo":
        if plant == "failing_test":
            name = f"{_w(rng, 1)}::tests::{token}"
            return ([f"test {name} ... FAILED"], ["", "failures:", f"    {name}", "",
                    f"test result: FAILED. {rng.randint(20, 300)} passed; 1 failed; 0 ignored"], token, name, "")
        if plant == "traceback":
            return ([f"thread 'main' panicked at src/main.rs:{rng.randint(10, 300)}:{rng.randint(1, 40)}:",
                     f"called `Result::unwrap()` on an `Err` value: NotFound(\"{token}\")",
                     "note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace"],
                    ["error: process didn't exit successfully: `target/debug/ledger` (exit status: 101)"], token,
                    f"panicked ... NotFound(\"{token}\")", "")
        return ([f"error[E0425]: cannot find value `{_w(rng, 1)}` in this scope",
                 f"  --> src/{_w(rng, 1)}.rs:{rng.randint(1, 300)}:{rng.randint(1, 40)}"],
                [f"error: could not compile `ledger` (lib) due to {n} previous errors"], str(n),
                f"due to {n} previous errors", "error")
    if kind == "lint":
        if plant == "failing_test":
            rule = rng.choice(("return-value", "arg-type", "attr-defined", "union-attr"))
            return ([f"src/{_w(rng, 1)}/{token}.py:{rng.randint(1, 300)}: error: Incompatible types in assignment  [{rule}]"],
                    ["Found 1 error in 1 file (checked 212 source files)"], token, f"{token}.py ... [{rule}]", "")
        if plant == "traceback":
            return ([], ["Oops! Something went wrong! :(", "", "ESLint: 8.57.0", "",
                         f"TypeError: Cannot read properties of undefined (reading '{token}')",
                         "    at Object.create (/work/proj/node_modules/eslint-plugin-x/lib/rule.js:41:22)"],
                    token, f"ESLint crash reading '{token}'", "")
        tool = rng.choice(("mypy", "tsc", "eslint"))
        line = {"mypy": f"Found {n} errors in {rng.randint(1, 9)} files (checked 212 source files)",
                "tsc": f"Found {n} errors in {rng.randint(1, 9)} files.",
                "eslint": f"✖ {n + 2} problems ({n} errors, 2 warnings)"}[tool]
        return [], [line], str(n), line, "error"
    if plant == "failing_test":
        return ([f"{camel}Test > {token}() FAILED", f"    org.opentest4j.AssertionFailedError: expected: <{n + 1}> but was: <{n}>"],
                [f"{rng.randint(200, 900)} tests completed, 1 failed", "BUILD FAILED in 52s"], token, f"{camel}Test > {token}()", "")
    if plant == "traceback":
        return ([f"Exception in thread \"main\" java.lang.IllegalStateException: shard {token} is closed",
                 f"\tat com.example.Ledger.flush(Ledger.java:{rng.randint(10, 300)})"], [], token,
                f"IllegalStateException: shard {token}", "")
    return ([f"src/main/java/com/example/{camel}.java:{rng.randint(1, 300)}: error: cannot find symbol"],
            [f"{n} errors", "BUILD FAILED in 9s"], str(n), f"{n} errors", "error")


def _log(rng: random.Random, kind: str, lines: int, plant: str | None) -> tuple[str, str, str, str]:
    filler = _filler(rng, kind, lines)
    body, tail, expect, what, word = _plant(rng, kind, plant) if plant else ([], [], "", "", "")
    start = {"go": ["go test ./..."], "jest": ["> proj@1.4.0 test", "> jest --ci"],
             "cargo": ["   Compiling ledger v0.3.1 (/work/proj)", "running tests"],
             "lint": ["$ mypy src && tsc --noEmit && eslint ."], "gradle": ["> Task :app:test"]}[kind]
    end = {"go": [f"ok  \texample.com/proj/{_w(rng, 1)}\t0.211s"],
           "jest": ["Test Suites: 12 passed, 12 total", f"Tests:       {lines} passed, {lines} total"],
           "cargo": [f"test result: ok. {lines} passed; 0 failed; 3 ignored; 0 measured; 0 filtered out"],
           "lint": [f"Success: no issues found in 212 source files", "✖ 2 problems (0 errors, 2 warnings)"],
           "gradle": ["BUILD SUCCESSFUL in 41s"]}[kind]
    at = rng.randint(0, len(filler))
    out = start + filler[:at] + body + filler[at:] + (tail if plant else end)
    return "\n".join(out) + "\n", expect, what, word or "error"


def cases(n: int = 60, seed: int = SEED) -> list[dict]:
    """n logs over each kind and plant in turn, each with a planted and a clean twin built from the same filler."""
    out = []
    for i in range(n):
        kind, plant = KINDS[i % len(KINDS)], PLANTS[(i // len(KINDS)) % len(PLANTS)]
        lines = random.Random(seed * 1000 + i).choice((40, 80, 150, 300, 600, 900, 1400))
        planted, expect, what, word = _log(random.Random(seed * 1000 + i), kind, lines, plant)
        clean, _, _, _ = _log(random.Random(seed * 1000 + i), kind, lines, None)
        out.append({"id": f"{i:03d}-{kind}-{plant}", "kind": kind, "plant": plant, "expect": expect, "word": word,
                    "planted": what, "text": planted, "clean": clean})
    return out
