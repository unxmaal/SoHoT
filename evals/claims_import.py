"""Import infovore's claims export into local-only cases: never into a git tree. #654.

    uv run python -m evals.claims_import [EXPORT] [--negatives PATH] [--out DIR]

EXPORT defaults to $LOCALHARNESS_HOME/import/claims.jsonl, the negatives to
claims-negatives.jsonl beside it (absent is fine), and DIR to
$LOCALHARNESS_HOME/cases/claims. The cases are verbatim chat text. The one
schema they share is written beside them as schema.json, which the lane serves.
Each review keeps its `interface`; one without reads as legacy. #661.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import yaml

LANE = "claims"
#: Fields a negatives line may carry that say why it is expected empty.
PROVENANCE = ("basis", "origin")


class Refused(RuntimeError):
    pass


def default_export() -> Path:
    from harness import paths
    return paths.home() / "import" / "claims.jsonl"


def default_negatives() -> Path:
    return default_export().with_name("claims-negatives.jsonl")


def default_out() -> Path:
    from evals.core import local_root
    return local_root() / LANE


def _in_git(path: Path) -> bool:
    probe = path
    while not probe.exists():
        probe = probe.parent
    try:
        got = subprocess.run(["git", "-C", str(probe), "rev-parse", "--is-inside-work-tree"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return got.returncode == 0 and got.stdout.strip() == "true"


def _rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def case_of(row: dict) -> dict:
    """One export line as a claims case."""
    empty = bool(row.get("expect_empty"))
    asserted = {"reviews": list(row.get("reviews") or [])}
    if empty:
        asserted["expect_empty"] = True
        asserted.update({k: row[k] for k in PROVENANCE if row.get(k)})
    return {"id": f"{LANE}-{row['id']}", "modality": LANE, "prompt": row["transcript"],
            "params": {"system": row["system"], "schema": row["schema"]}, "assert": asserted}


def run(export: Path, negatives: Path | None, out: Path) -> list[Path]:
    """Replace `out` with one case per export line and their schema; refuses an `out` inside a git work tree."""
    out = Path(out).resolve()
    if _in_git(out):
        raise Refused(f"{out} is inside a git work tree; claims cases are private and stay local")
    rows = _rows(Path(export)) + (_rows(Path(negatives)) if negatives else [])
    cases = [case_of(r) for r in rows]
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise Refused("the export and the negatives repeat a case id")
    schemas = {json.dumps(c["params"]["schema"], sort_keys=True) for c in cases}
    if len(schemas) > 1:
        raise Refused(f"the export's cases disagree on the schema ({len(schemas)} distinct); "
                      "the lane serves one")
    from harness.checks import claims as claims_check
    for c in cases:
        a = c["assert"]
        claims_check.validate_case(c["params"]["system"], c["params"]["schema"], a["reviews"],
                                   a.get("expect_empty"))
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if cases:
        claims_check.write_schema(out, cases[0]["params"]["schema"])
    written = []
    for c in sorted(cases, key=lambda c: c["id"]):
        path = out / f"{c['id']}.yaml"
        path.write_text(yaml.safe_dump(c, sort_keys=False, allow_unicode=True, width=100),
                        encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.claims_import")
    ap.add_argument("export", nargs="?", default=None)
    ap.add_argument("--negatives", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    export = Path(a.export) if a.export else default_export()
    if not export.is_file():
        print(f"no export at {export}")
        return 1
    negatives = Path(a.negatives) if a.negatives else export.with_name("claims-negatives.jsonl")
    try:
        written = run(export, negatives, Path(a.out) if a.out else default_out())
    except (Refused, ValueError) as exc:
        print(f"refused: {exc}")
        return 1
    loaded = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in written]
    empty = sum(1 for c in loaded if c["assert"].get("expect_empty"))
    from collections import Counter

    from harness.checks.claims import interface_of
    per = Counter(interface_of(r) for c in loaded for r in c["assert"]["reviews"])
    split = ", ".join(f"{k} {v}" for k, v in sorted(per.items()))
    print(f"{len(loaded) - empty} reviewed, {empty} expect_empty, {sum(per.values())} reviews "
          f"({split or 'none'}) under {written[0].parent if written else '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
