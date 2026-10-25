"""`soh craft validate`: build each craft run book's controls headless on the installed app and check each comes out as named (#1209)."""
from __future__ import annotations

import json
from pathlib import Path

from harness.commands.common import err

CASES = Path(__file__).resolve().parents[2] / "evals" / "cases" / "craft"


def add_parser(sub) -> None:
    p = sub.add_parser("craft", help="the craft lane's run books: validate builds each reference, an empty document "
                       "and each planted near-miss headless and checks the reference alone passes (#1209)")
    p.add_argument("action", choices=("validate",))
    p.add_argument("--case", default="", help="one run book id (default: every run book)")
    p.add_argument("--revalidate", action="store_true", help="run on whatever release is installed and, when every "
                   "control comes out as named, print the release block to pin it")
    p.add_argument("--record", default="", help="also write each control's document.inspect JSON to this folder")
    p.add_argument("--cases", default=str(CASES), help="the craft run books (default: evals/cases/craft)")
    p.set_defaults(func=cmd_craft)


def _one(case, a) -> dict:
    """One run book's validation: its controls, or why none ran, and the pin to record when revalidated."""
    from evals import craft
    app = craft.app_of(case)
    out = {"case": case.id, "app": app.name, "controls": [], "error": "", "pin": None}
    argv = craft.binary(app)
    if not argv:
        out["error"] = (f"{app.cli} is not installed; install {case.params['release']['asset']} "
                        f"(sha256 {case.params['release']['sha256']}) or set SOHOT_{app.name.upper()}_CLI")
        return out
    try:
        version = craft.installed_version(argv) if a.revalidate else craft.check_pin(case, argv)["version"]
        out["controls"] = craft.validate(case, argv, record=Path(a.record) if a.record else None)
    except craft.CraftError as exc:
        out["error"] = str(exc)
        return out
    if a.revalidate and all(r["ok"] for r in out["controls"]):
        out["pin"] = {"version": version, "binary_sha256": craft.file_sha256(Path(argv[0]))}
    return out


def cmd_craft(a) -> int:
    from evals import core
    cases = [c for c in core.load_cases(a.cases) if c.modality == "craft" and (not a.case or c.id == a.case)]
    if not cases:
        return err(f"no craft run book {a.case} in {a.cases}" if a.case else f"no craft run books in {a.cases}")
    done = [_one(c, a) for c in cases]
    bad = sum(1 for d in done if d["error"]) + sum(1 for d in done for r in d["controls"] if not r["ok"])
    if getattr(a, "json", False):
        print(json.dumps(done, indent=1))
        return 1 if bad else 0
    for d in done:
        if d["error"]:
            print(f"{d['case']}: {d['error']}")
        for r in d["controls"]:
            want = "pass" if r["control"] == "reference" else "fail" + (
                f" on {', '.join(r['expected'])}" if r["expected"] else "")
            print(f"  {'ok  ' if r['ok'] else 'BAD '} {d['case']} {r['control']}: wants {want}; {r['detail']}")
        if d["pin"]:
            print(f"{d['case']}: every control holds; pin it with params.release {json.dumps(d['pin'])} plus that "
                  f"release's tag, asset and SHA256SUMS.txt line")
    return 1 if bad else 0
