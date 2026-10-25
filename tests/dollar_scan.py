"""AST scan: a dollar amount formatted beside a Claude usage field in an output string. #976."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from tests import layout_scan

CLAUDE = re.compile(r"cloud|claude|ccusage|otel|cost_usd|displaced|mapped|token|api[ _-]?(request|equivalent)"
                    r"|list price|opus|sonnet|haiku|per M\b", re.I)
MONEY_WORDS = re.compile(r"dollar|\bUSD\b|API-equivalent|list price", re.I)
MONEY_FORMAT = re.compile(r"\$\{[^}]*:[^}]*[dfg]\}|\$%[-+ #,.\d]*[dfg]|\$\{\}")
#: The API credit ledger is real prepaid money, the one place dollars are reported (#1214).
SKIP = ("evals.cases", "harness.api_spend", "harness.commands.api_spend")


@dataclass(frozen=True)
class Hit:
    module: str
    line: int
    text: str


def _shell_variable(fv: ast.FormattedValue) -> bool:
    """`${NAME_ENV}`: a constant naming an environment variable, not an amount."""
    name = getattr(fv.value, "id", getattr(fv.value, "attr", ""))
    return fv.format_spec is None and bool(name) and name.isupper()


def _dollar_fstring(node) -> bool:
    if not isinstance(node, ast.JoinedStr):
        return False
    v = node.values
    return any(isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.endswith("$")
               and isinstance(b, ast.FormattedValue) and not _shell_variable(b) for a, b in zip(v, v[1:]))


def _formatters(tree) -> set[str]:
    """Functions in the module that return a formatted dollar amount."""
    out = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for r in ast.walk(fn):
                if isinstance(r, ast.Return) and r.value is not None and any(
                        _dollar_fstring(n) for n in ast.walk(r.value)):
                    out.add(fn.name)
    return out


def _docstrings(tree) -> set[int]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def scan_source(source: str, module: str = "<src>") -> list[Hit]:
    tree = ast.parse(source)
    parents = {id(c): p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    formatters, docs = _formatters(tree), _docstrings(tree)

    def context(node):
        """The output string a dollar site sits in: its outermost enclosing f-string, else the site itself."""
        best, cur = node, node
        while id(cur) in parents:
            cur = parents[id(cur)]
            if isinstance(cur, ast.JoinedStr):
                best = cur
        return best

    hits, seen = [], set()
    for n in ast.walk(tree):
        site = None
        if _dollar_fstring(n):
            site = n
        elif isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) in formatters:
            site = n
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and \
                not isinstance(parents.get(id(n)), ast.JoinedStr) and \
                (MONEY_FORMAT.search(n.value) or MONEY_WORDS.search(n.value)):
            site = n
        if site is None:
            continue
        ctx = context(site)
        text = ast.get_source_segment(source, ctx) or ""
        if not CLAUDE.search(text) or (ctx.lineno, text) in seen:
            continue
        seen.add((ctx.lineno, text))
        hits.append(Hit(module, ctx.lineno, text.splitlines()[0][:160]))
    return sorted(hits, key=lambda h: h.line)


def scan(root=layout_scan.REPO) -> list[Hit]:
    out = []
    for mod, src in sorted(layout_scan.code_modules(root).items()):
        if mod.startswith(SKIP):
            continue
        out.extend(scan_source(src, mod))
    return out
