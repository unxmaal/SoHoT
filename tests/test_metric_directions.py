"""Every metric name an eval can emit declares a direction, so a new one fails here instead of warning at rank time (#879)."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCES = ("evals", "harness/checks")


def _metricish(node) -> bool:
    name = node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")
    return name.endswith("metrics")


def _numeric(value) -> bool:
    return not isinstance(value, (ast.List, ast.ListComp, ast.Tuple, ast.Dict, ast.Set))


def _keys(d: ast.Dict):
    for k, v in zip(d.keys, d.values):
        if isinstance(k, ast.Constant) and isinstance(k.value, str) and _numeric(v):
            yield k.value


def _subscript_key(t, holders) -> str:
    if (isinstance(t, ast.Subscript) and holders(t.value)
            and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str)):
        return t.slice.value
    return ""


def emitted_metrics(src: str, rel: str) -> dict[str, str]:
    """Literal metric names written into a metrics dict, each with where: `x.metrics = {...}`, `metrics["k"] = v`,
    `metrics.update({...})`, `metrics={...}`, `{"metrics": {...}}`, and dicts built in a *metrics* function or rollup."""
    found: dict[str, str] = {}

    def add(name: str, node) -> None:
        if name:
            found.setdefault(name, f"{rel}:{node.lineno}")

    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                if _metricish(t):
                    for d in ast.walk(n.value):
                        if isinstance(d, ast.Dict):
                            for k in _keys(d):
                                add(k, n)
                if _numeric(n.value):
                    add(_subscript_key(t, _metricish), n)
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "update" and _metricish(n.func.value)):
            for a in n.args:
                if isinstance(a, ast.Dict):
                    for k in _keys(a):
                        add(k, n)
        elif isinstance(n, ast.keyword) and n.arg == "metrics" and isinstance(n.value, ast.Dict):
            for k in _keys(n.value):
                add(k, n.value)
        elif isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value == "metrics" and isinstance(v, ast.Dict):
                    for name in _keys(v):
                        add(name, v)
        if isinstance(n, ast.FunctionDef) and ("metrics" in n.name or n.name == "rollup"):
            local = {t.id for a in ast.walk(n) if isinstance(a, (ast.Assign, ast.AnnAssign))
                     and isinstance(a.value, ast.Dict)
                     for t in (a.targets if isinstance(a, ast.Assign) else [a.target])
                     if isinstance(t, ast.Name)}
            for a in ast.walk(n):
                if isinstance(a, ast.Return) and isinstance(a.value, ast.Dict):
                    for k in _keys(a.value):
                        add(k, a)
                elif isinstance(a, (ast.Assign, ast.AnnAssign)) and a.value is not None:
                    for t in (a.targets if isinstance(a, ast.Assign) else [a.target]):
                        if isinstance(t, ast.Name) and t.id in local and isinstance(a.value, ast.Dict):
                            for k in _keys(a.value):
                                add(k, a)
                        if _numeric(a.value):
                            add(_subscript_key(t, lambda v: isinstance(v, ast.Name) and v.id in local), a)
    return found


def _repo_metrics() -> dict[str, str]:
    out: dict[str, str] = {}
    for top in SOURCES:
        for p in sorted((REPO / top).rglob("*.py")):
            for name, where in emitted_metrics(p.read_text(encoding="utf-8"), p.relative_to(REPO).as_posix()).items():
                out.setdefault(name, where)
    return out


def test_every_shape_of_metric_write_is_found():
    src = ("out.metrics = {'a': 1}\n"
           "metrics['b'] = 2\n"
           "row.metrics.update({'c': 3})\n"
           "Result(metrics={'d': 4})\n"
           "rec = {'metrics': {'e': 5}}\n"
           "def _metrics(self):\n    out = {'f': 6}\n    out['g'] = 7\n    return out\n"
           "def extra_metrics(self):\n    return {'h': 8}\n"
           "def rollup(steps):\n    return {'i': 9}\n")
    assert sorted(emitted_metrics(src, "m.py")) == list("abcdefghi")


def test_what_is_not_a_metric_write_stays_quiet():
    src = ("options = {'a': 1}\n"
           "row['b'] = 2\n"
           "settings.update({'c': 3})\n"
           "out.metrics = {'decisions': [[0.5, 1]]}\n"
           "def build(self):\n    out = {'d': 4}\n    return out\n")
    assert emitted_metrics(src, "m.py") == {}


def test_the_repo_scan_sees_the_metrics_it_must():
    got = _repo_metrics()
    for name in ("wer", "cer", "ink", "attempts", "agent_steps", "needle_peak_mb", "decide_accuracy", "pii_f1"):
        assert name in got, f"the scanner lost {name}; it would pass by seeing nothing"


def test_every_emitted_metric_declares_a_direction():
    from evals.core import _COMPANIONS, METRIC_DIRECTION
    missing = [f"{where}: {name}" for name, where in sorted(_repo_metrics().items())
               if name not in METRIC_DIRECTION and name not in _COMPANIONS]
    assert not missing, ("metrics with no METRIC_DIRECTION entry (direction_of would warn and "
                         "assume lower):\n" + "\n".join(missing))


def test_attempts_is_lower_is_better():
    from evals.core import METRIC_DIRECTION
    assert METRIC_DIRECTION.get("attempts") == "lower"
