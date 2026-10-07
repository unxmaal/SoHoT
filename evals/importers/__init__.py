"""Case importers: one module per source, writing evals/cases/<lane>/<source>/ deterministically. #603.

A source module defines LANE, DATASET, URL, LICENSE, REVISION (pinned, 40 hex),
SOURCE (e.g. "hf:<id>"), fetch() -> rows at REVISION, and convert(row) ->
Imported | None. Lane checks for the negative control live beside them.
"""
from __future__ import annotations

import importlib
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from evals.benchmark_import import ALLOWED_LICENSES

CASES = Path(__file__).resolve().parent.parent / "cases"
MARK = "Imported by evals/importers"


@dataclass(frozen=True)
class Source:
    name: str
    lane: str


#: One line per importer; keep it a flat list so parallel additions merge cleanly.
REGISTRY = [
    Source("leetcode", "code"),
]


@dataclass(frozen=True)
class Imported:
    case: dict
    reference: str | None = None


def module(name: str):
    """The importer module registered as `name`."""
    if name not in {s.name for s in REGISTRY}:
        known = ", ".join(s.name for s in REGISTRY)
        raise ValueError(f"no importer {name!r}; known: {known}")
    return importlib.import_module(f"evals.importers.{name}")


def provenance(mod, item, transform: str, date: str = "") -> dict:
    """The attribution block every imported case carries."""
    return {"dataset": mod.DATASET, "url": mod.URL, "license": mod.LICENSE,
            "source": mod.SOURCE, "revision": mod.REVISION, "item": str(item),
            "date": date, "transform": transform, "importer": mod.__name__}


def _dump(mod, case: dict) -> str:
    head = (f"# {mod.DATASET}, {mod.LICENSE} ({mod.URL}).\n"
            f"# {MARK} from {mod.SOURCE}@{mod.REVISION}; re-import, do not edit.\n")
    return head + yaml.safe_dump(case, sort_keys=False, allow_unicode=True, width=100)


def write(mod, name: str, made: list[Imported], root: Path = CASES) -> list[Path]:
    """Replace evals/cases/<lane>/<name>/ with `made`, in id order; returns the case files."""
    out = Path(root) / mod.LANE / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    written = []
    for one in sorted(made, key=lambda m: m.case["id"]):
        path = out / f"{one.case['id']}.yaml"
        path.write_text(_dump(mod, one.case), encoding="utf-8")
        if one.reference is not None:
            (out / "reference").mkdir(exist_ok=True)
            (out / "reference" / f"{one.case['id']}.py").write_text(
                f"# {MARK} from {mod.SOURCE}@{mod.REVISION}.\n" + one.reference,
                encoding="utf-8")
        written.append(path)
    return written


def run(name: str, root: Path = CASES, rows=None) -> list[Path]:
    """Fetch (unless `rows` is given), convert and write one source's cases."""
    mod = module(name)
    if mod.LICENSE not in ALLOWED_LICENSES:
        raise ValueError(f"{name} is {mod.LICENSE}, which is not an allowed license")
    made = [m for m in (mod.convert(r) for r in (mod.fetch() if rows is None else rows)) if m]
    ids = [m.case["id"] for m in made]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{name}: duplicate case ids")
    return write(mod, name, made, root)


def negative_control(cases, responders: dict, passes) -> dict[str, tuple[int, int]]:
    """responder name -> (cases passed, cases) where responders[name](case) is an answer."""
    out = {}
    for rname, answer in responders.items():
        out[rname] = (sum(1 for c in cases if passes(c, answer(c))), len(cases))
    return out
