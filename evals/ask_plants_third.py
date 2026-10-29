"""A third planted-failure set for `soh ask`: unittest, rspec, C build/ctest and terraform logs. #1335."""
from __future__ import annotations

import random

from evals.ask_plants import PLANTS

KINDS = ("unittest", "rspec", "cbuild", "terraform")
QUESTION = "Summarise any failures in this output: which tests or steps broke, any crash, and how many errors."
SEED = 4711

_WORDS = ("acorn", "beacon", "canyon", "dynamo", "eclipse", "falcon", "glacier", "hollow", "iris", "jasper",
          "kelp", "lagoon", "magnet", "nectar", "onyx", "prism", "quill", "raven", "saffron", "thistle",
          "ultra", "velvet", "walnut", "xylem", "yonder", "zinc", "almond", "birch", "comet", "drift")


def _w(rng: random.Random, n: int = 2, sep: str = "_") -> str:
    return sep.join(rng.choice(_WORDS) for _ in range(n))


def _cls(rng: random.Random) -> str:
    return "".join(rng.choice(_WORDS).capitalize() for _ in range(2))


def _filler(rng: random.Random, kind: str, n: int) -> list[str]:
    out = []
    for _ in range(n):
        r = rng.random()
        if kind == "unittest":
            t = f"test_{_w(rng)} (tests.test_{_w(rng, 1)}.{_cls(rng)}Test.test_{_w(rng)})"
            out.append(f"{t} ... ok" if r < 0.8 else f"{t} ... skipped 'needs network'" if r < 0.9 else
                       f"{t} ... expected failure")
        elif kind == "rspec":
            out.append("." * rng.randint(10, 70) if r < 0.6 else
                       f"  {_cls(rng)} {_w(rng, 3, ' ')}" if r < 0.85 else
                       f"    # Temporarily skipped with xit" if r < 0.92 else
                       f"DEPRECATION WARNING: {_w(rng, 2, ' ')} is deprecated (called from block at spec/{_w(rng, 1)}_spec.rb:{rng.randint(1, 99)})")
        elif kind == "cbuild":
            i = rng.randint(1, 40)
            out.append(f"cc -O2 -Wall -c src/{_w(rng, 1)}.c -o build/{_w(rng, 1)}.o" if r < 0.6 else
                       f"src/{_w(rng, 1)}.c:{rng.randint(1, 400)}:{rng.randint(1, 30)}: warning: unused variable "
                       f"'{_w(rng, 1)}' [-Wunused-variable]" if r < 0.75 else
                       f"{i:3d}/40 Test #{i:2d}: {_w(rng)} {'.' * rng.randint(5, 30)}   Passed    {rng.uniform(0, 2):.2f} sec"
                       if r < 0.95 else f"{rng.randint(1, 9)} warnings generated.")
        else:
            res = f"aws_{rng.choice(('s3_bucket', 'iam_role', 'lambda_function', 'sqs_queue'))}.{_w(rng)}"
            out.append(f"{res}: Refreshing state... [id={_w(rng, 2, '-')}]" if r < 0.7 else
                       f"{res}: Still creating... [{rng.randint(10, 90)}s elapsed]" if r < 0.85 else
                       f"{res}: Creation complete after {rng.randint(1, 90)}s [id={_w(rng, 2, '-')}]")
    return out


def _plant(rng: random.Random, kind: str, plant: str) -> tuple[list[str], list[str], str, str, str]:
    """(body lines, tail lines, expected token, what was planted, the count's word)."""
    token = _w(rng, 3)
    n = rng.randint(2, 64)
    if kind == "unittest":
        if plant == "failing_test":
            name = f"test_{token}"
            return ([f"{name} (tests.test_ledger.LedgerTest.{name}) ... FAIL"],
                    ["=" * 70, f"FAIL: {name} (tests.test_ledger.LedgerTest.{name})", "-" * 70,
                     "AssertionError: 3 != 4", "", "Ran 212 tests in 3.104s", "", "FAILED (failures=1)"],
                    name, f"FAIL: {name}", "")
        if plant == "traceback":
            return (["Traceback (most recent call last):", '  File "/srv/app/spool.py", line 88, in flush',
                     "    fh.write(blob)", f"OSError: [Errno 28] No space left on device: '/var/spool/{token}'"],
                    [], token, f"OSError ... '/var/spool/{token}'", "")
        return [], ["Ran 212 tests in 3.104s", "", f"FAILED (errors={n})"], str(n), f"FAILED (errors={n})", "error"
    if kind == "rspec":
        if plant == "failing_test":
            return ([], ["Failures:", "", f"  1) Ledger {token.replace('_', ' ')} flushes", "     Failure/Error: expect(x).to eq(4)",
                         "", "Failed examples:", "", f"rspec ./spec/models/{token}_spec.rb:42 # Ledger flushes"],
                    token, f"rspec ./spec/models/{token}_spec.rb:42", "")
        if plant == "traceback":
            return ([f"/srv/app/lib/ledger.rb:12:in `flush': undefined method `{token}' for nil:NilClass (NoMethodError)",
                     "\tfrom /srv/app/lib/runner.rb:40:in `call'"], [], token, f"undefined method `{token}' (NoMethodError)", "")
        return [], [f"Finished in {rng.uniform(1, 90):.2f} seconds", f"212 examples, {n} failures, 3 pending"], str(n), \
            f"212 examples, {n} failures", "fail"
    if kind == "cbuild":
        if plant == "failing_test":
            return ([f" 7/40 Test  #7: {token} {'.' * 12}***Failed    0.04 sec"],
                    ["97% tests passed, 1 tests failed out of 40", "The following tests FAILED:", f"\t  7 - {token} (Failed)"],
                    token, f"Test #7: {token} ***Failed", "")
        if plant == "traceback":
            return ([f"{token}: src/pool.c:{rng.randint(10, 400)}: pool_take: Assertion `slot < cap' failed.",
                     "Aborted (core dumped)"], ["make: *** [Makefile:31: check] Error 134"], token,
                    f"{token}: ... Assertion `slot < cap' failed.", "")
        return ([f"src/{_w(rng, 1)}.c:{rng.randint(1, 400)}:{rng.randint(1, 30)}: error: use of undeclared identifier '{_w(rng, 1)}'"],
                [f"{n} errors generated.", "make: *** [Makefile:12: build/app] Error 1"], str(n), f"{n} errors generated.", "error")
    if plant == "failing_test":
        return ([], ["", f"Error: creating S3 Bucket ({token}): BucketAlreadyExists", "",
                     f"  with aws_s3_bucket.{token},", "  on main.tf line 12"], token, f"Error: creating S3 Bucket ({token})", "")
    if plant == "traceback":
        return ([], ["", "Stack trace from the terraform-provider-aws plugin:", "",
                     "panic: runtime error: invalid memory address or nil pointer dereference",
                     f"github.com/hashicorp/terraform-provider-aws/internal/service/{token}.resourceRead(...)",
                     "", "Error: The terraform-provider-aws plugin crashed!"], token, f"provider crash in {token}", "")
    return ([], [f"{n} issue(s) found:", "", f"Warning: module \"{token}\" should specify a version (terraform_module_version)"],
            str(n), f"{n} issue(s) found", "issue")


def _log(rng: random.Random, kind: str, lines: int, plant: str | None) -> tuple[str, str, str, str]:
    filler = _filler(rng, kind, lines)
    body, tail, expect, what, word = _plant(rng, kind, plant) if plant else ([], [], "", "", "")
    start = {"unittest": ["$ python -m unittest -v"], "rspec": ["$ bundle exec rspec"],
             "cbuild": ["$ make check"], "terraform": ["$ terraform apply -auto-approve && tflint"]}[kind]
    end = {"unittest": ["", f"Ran {lines} tests in 3.104s", "", "OK (skipped=3, expected failures=1)"],
           "rspec": ["Pending: (Failures listed here are expected and do not affect your suite's status)",
                     f"Finished in 12.5 seconds", f"{lines} examples, 0 failures, 3 pending"],
           "cbuild": ["100% tests passed, 0 tests failed out of 40"],
           "terraform": ["Apply complete! Resources: 3 added, 0 changed, 0 destroyed."]}[kind]
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
