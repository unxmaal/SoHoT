"""LeetCodeDataset (Xia et al. 2025) as code cases: the dataset's own asserts, its completion as reference. #603."""
from __future__ import annotations

import ast
import json
import re
import sys
import warnings

from evals.importers import Imported, provenance

LANE = "code"
SOURCE = "hf:newfacade/LeetCodeDataset"
DATASET = "LeetCodeDataset (newfacade, Xia et al. 2025)"
URL = "https://huggingface.co/datasets/newfacade/LeetCodeDataset"
LICENSE = "Apache-2.0"
REVISION = "215604aeed660029df7de2fea5a4d7b6ed476a08"
FILES = f"https://huggingface.co/datasets/newfacade/LeetCodeDataset/resolve/{REVISION}"
#: The test split is the whole post-2024-07 temporal holdout; train is read from its dated tail.
TRAIN_SINCE = "2024-01-01"
TRAIN_TAIL_BYTES = 12_000_000
MAX_CHECKS = 10
MAX_CHECK_CHARS = 300
TRANSFORM = (f"problem_description and starter_code as the prompt; the first {MAX_CHECKS} "
             f"check(candidate) asserts under {MAX_CHECK_CHARS} chars with candidate -> "
             f"entry_point; prompt imports + completion as reference")
_NODE = re.compile(r"\b(ListNode|TreeNode|Node)\b")
_ALLOWED = {"candidate", "True", "False", "None"}


def _get(url: str, headers=None) -> bytes:
    import httpx
    r = httpx.get(url, headers=headers or {}, timeout=300, follow_redirects=True)
    r.raise_for_status()
    return r.content


def _jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def fetch() -> list[dict]:
    """The test split whole, and train rows dated TRAIN_SINCE or later, at REVISION."""
    test = _jsonl(_get(f"{FILES}/LeetCodeDataset-test.jsonl").decode("utf-8"))
    tail = _get(f"{FILES}/LeetCodeDataset-train.jsonl",
                {"Range": f"bytes=-{TRAIN_TAIL_BYTES}"}).decode("utf-8", "replace")
    train = _jsonl(tail.split("\n", 1)[1])
    if not train or train[0]["estimated_date"] >= TRAIN_SINCE:
        raise RuntimeError("TRAIN_TAIL_BYTES does not reach back to TRAIN_SINCE; raise it")
    return [r for r in train if r["estimated_date"] >= TRAIN_SINCE] + test


def assert_to_check(stmt: ast.stmt, entry_point: str) -> str | None:
    """An assert's expression with candidate -> entry_point; None if it names any helper."""
    if not isinstance(stmt, ast.Assert):
        return None
    names = {n.id for n in ast.walk(stmt.test) if isinstance(n, ast.Name)}
    if names - _ALLOWED:
        return None
    target = ast.parse(entry_point, mode="eval").body

    class Swap(ast.NodeTransformer):
        def visit_Name(self, node):
            return target if node.id == "candidate" else node

    return ast.unparse(Swap().visit(stmt.test))


def _expected(check: str):
    tree = ast.parse(check, mode="eval").body
    if isinstance(tree, ast.Compare) and len(tree.ops) == 1 and isinstance(tree.ops[0], ast.Eq):
        try:
            return repr(ast.literal_eval(tree.comparators[0]))
        except ValueError:
            return None
    return None


def checks_of(row: dict) -> list[str]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(row["test"])
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "check"), None)
    out = []
    for stmt in fn.body if fn else []:
        c = assert_to_check(stmt, row["entry_point"])
        if c and len(c) <= MAX_CHECK_CHARS:
            out.append(c)
        if len(out) >= MAX_CHECKS:
            break
    return out


def convert(row: dict) -> Imported | None:
    """One row as a code case, or None if it needs a helper, is constant-passable or fails its own reference."""
    from harness.checks import code
    starter = row["starter_code"]
    if not starter.lstrip().startswith("class Solution") or _NODE.search(starter):
        return None
    checks = checks_of(row)
    if len(checks) < 3 or len({_expected(c) for c in checks} - {None}) < 2:
        return None
    reference = row["prompt"].split("\nclass ListNode")[0].rstrip() + "\n\n" + row["completion"]
    if not code.check(reference, checks).ok:
        return None
    qid = row["question_id"]
    prompt = (f"{row['problem_description'].strip()}\n\n"
              f"Write the solution in Python as this class, with any imports it needs:\n\n"
              f"```python\n{starter.rstrip()}\n```\n\nReturn only the code.")
    case = {"id": f"lc{qid}", "modality": "code", "prompt": prompt, "assert": {"checks": checks},
            "attribution": provenance(sys.modules[__name__], qid, TRANSFORM, row["estimated_date"][:10])}
    return Imported(case, reference.rstrip() + "\n")


_CONSTANT = "class Solution:\n    def __getattr__(self, name):\n        return lambda *a, **k: {value}\n"


def _reference(case) -> str:
    return (case.source.parent / "reference" / f"{case.id}.py").read_text(encoding="utf-8")


#: The negative control: the reference must pass, a constant answer must not.
RESPONDERS = {
    "reference": _reference,
    "none": lambda case: _CONSTANT.format(value="None"),
    "zero": lambda case: _CONSTANT.format(value="0"),
}


def passes(case, answer: str) -> bool:
    from harness.checks import code
    return code.check(answer, case.assertions["checks"]).ok
