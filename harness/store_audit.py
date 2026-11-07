"""Where code still speaks only SQLite: direct sqlite3 use around the store seam and SQLite-only SQL. #1507."""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

from harness import paths

#: The seam itself, which speaks both dialects on purpose.
SEAM = {"harness/store.py", "harness/store_copy.py", "harness/store_audit.py",
        "harness/memory_store/connection.py"}

#: SQL text only SQLite runs (store.COMPAT gives Postgres instr, json_extract and group_concat).
SQL_ONLY = {
    "pragma": re.compile(r"\bPRAGMA\b"),
    "sqlite_master": re.compile(r"\bsqlite_(?:master|sequence|schema)\b"),
    "uri_mode": re.compile(r"\?(?:mode=ro|immutable=1)\b"),
    "json_each": re.compile(r"\bjson_(?:each|group_array|object)\s*\(", re.I),
    "sql_time": re.compile(r"\b(?:julianday|unixepoch)\s*\(|\bdatetime\s*\(\s*'now'", re.I),
}
_SQLISH = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE|PRAGMA|CREATE)\b|\?mode=|immutable=1")


def _files(root: Path):
    for top in ("harness", "evals"):
        for f in sorted((root / top).rglob("*.py")):
            rel = f.relative_to(root).as_posix()
            if rel not in SEAM and "/cases/" not in rel:
                yield rel, f


def _strings(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            yield node.lineno, text


def scan(root: Path | None = None) -> list[tuple[str, int, str]]:
    """(file, line, kind) for every SQLite-only construct outside the seam."""
    root = Path(root or paths.REPO)
    out = []
    for rel, f in _files(root):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if node.func.attr == "connect" and isinstance(owner, ast.Name) and owner.id == "sqlite3":
                    out.append((rel, node.lineno, "sqlite3_connect"))
                elif node.func.attr == "backup":
                    out.append((rel, node.lineno, "backup"))
            elif isinstance(node, ast.ExceptHandler) and node.type is not None:
                if "sqlite3." in ast.unparse(node.type):
                    out.append((rel, node.lineno, "except_sqlite3"))
        for line, text in _strings(tree):
            if not _SQLISH.search(text):
                continue
            for kind, rx in SQL_ONLY.items():
                if rx.search(text):
                    out.append((rel, line, kind))
    return sorted(set(out))


def counts(found=None) -> dict[str, int]:
    return dict(sorted(Counter(k for _, _, k in (found if found is not None else scan())).items()))


def report_text(found) -> str:
    lines = [f"{k:<16} {n}" for k, n in counts(found).items()]
    lines += [f"  {f}:{line} {k}" for f, line, k in found]
    return "\n".join(lines)


if __name__ == "__main__":
    print(report_text(scan()))
