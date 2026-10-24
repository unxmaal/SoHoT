"""Every outcome-gating constant is a hypothesis: its range, the lanes it shapes, and the limit that shows it binding (#636).

This is the registry `soh sensitivity` sweeps (#98). A knob with a `probe` is
swept offline against cached data; a knob with a `limit` is one an eval can hit,
and the limit is the predicate name a result row or a verdict records when it
does (`timeout_s>180`, `max_tokens.code>32768`, `ceiling_gb:>66`).

`inventory()` finds the numeric values whose names say they gate something:
constants, table entries, argument and field defaults, call literals and environment defaults, whatever their name. Every one is either registered in an area module of this package, named in
its NOT_GATING with a reason, or in the shrinking backlog the tier-1 test holds.
"""
from __future__ import annotations

import ast
import importlib
import inspect as _inspect
import os
import pkgutil
import re
from pathlib import Path

from harness.knobs.base import GIB, LIMIT, MACHINE, REQUEST_LANES, TEXT_LANES, UNITS, Knob, _k  # noqa: F401

REPO = Path(__file__).resolve().parent.parent.parent

#: Name words that mark a constant as one that gates an outcome.
GATING_WORDS = frozenset({"MAX", "MIN", "TIMEOUT", "CAP", "LIMIT", "FLOOR", "CEILING", "BUDGET",
                          "THRESHOLD", "TOLERANCE", "TEMPERATURE", "TOKENS", "RESERVE", "ALPHA",
                          "CUTOFF", "MARGIN", "STEPS", "FRACTION", "WER", "CER", "INK", "MOTION",
                          "STDDEV", "F1", "DAYS", "SHARED", "POPULATION", "VOTES", "RETRIES",
                          "ATTEMPTS", "GRACE", "WAIT", "DELAY", "POLL", "INTERVAL", "STALL", "SECONDS",
                          "EFFECT", "CTX", "Z", "IDLE", "SLEEP"})
#: Name endings and phrases that mark a gate: seconds, a rate, a per-token or per-GiB allowance.
GATING_SUFFIXES = ("_S",)
GATING_PHRASES = ("PER_TOKEN", "PER_GIB")
#: Argument names whose numeric default or call-site literal gates an outcome.
GATING_PARAMS = frozenset({"timeout", "grace", "poll", "settle_s", "max_tokens", "max_new_tokens",
                           "limit", "levels"})
_UPPER = re.compile(r"_?[A-Z][A-Z0-9_]*")
_SITE = re.compile(r"(?P<rel>[\w/]+\.py):(?P<name>[\w.]+)(?P<keys>(?:\[[\w.-]+\])*)(?:\((?P<param>\w+)\))?")
_SHELL_DEFAULT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):?[-=](-?[0-9]+(?:\.[0-9]+)?)\}")


def areas() -> dict:
    """Each area module of the registry, by name: every module in this package but base."""
    names = sorted(m.name for m in pkgutil.iter_modules(__path__) if m.name != "base" and not m.name.startswith("_"))
    return {n: importlib.import_module(f"{__name__}.{n}") for n in names}


def entries(module) -> list[str]:
    """The knob names an area module registers, in its own order."""
    return [e[0] if isinstance(e, tuple) else e.name for e in module.KNOBS]


def _limit_names(k) -> list[str]:
    """Every predicate name a knob's limit is recorded under: the bare name and each lane's."""
    if not k.limit:
        return []
    return [k.limit_name("")] + [k.limit_name(lane) for lane in k.lanes if "{lane}" in k.limit]


def collect(lists: dict) -> tuple[dict, dict]:
    """(knobs by name, area by knob name) from each area's entries; a name in two places is refused."""
    found, where = {}, {}
    for area, items in lists.items():
        for item in items:
            k = item[1] if isinstance(item, tuple) else item
            if k.name in where:
                raise ValueError(f"knob {k.name!r} is registered in both {where[k.name]} and {area}")
            found[k.name], where[k.name] = k, area
    owner = {}
    for k in found.values():
        if k.binds_via and not getattr(found.get(k.binds_via), "limit", ""):
            raise ValueError(f"knob {k.name!r} binds via {k.binds_via!r}, which is no knob with a limit")
        for name in _limit_names(k):
            if owner.setdefault(name, k.name) != k.name:
                raise ValueError(f"knobs {owner[name]!r} and {k.name!r} both record limit {name!r}; a limit has one value and one unit (#752)")
    return dict(sorted(found.items())), where


def _not_gating(modules: dict) -> dict[str, str]:
    out, where = {}, {}
    for area, mod in modules.items():
        for site, why in getattr(mod, "NOT_GATING", {}).items():
            if site in where:
                raise ValueError(f"NOT_GATING site {site!r} is in both {where[site]} and {area}")
            out[site], where[site] = why, area
    return out


_AREAS = areas()
KNOBS, AREA = collect({n: m.KNOBS for n, m in _AREAS.items()})

#: The value a knob had on receipts written before it was recorded there, by knob name. #693.
UNRECORDED = {k.name: k.unrecorded for k in KNOBS.values() if k.unrecorded is not None}

#: Constants the inventory finds whose name says gate and whose value does not, each with why.
NOT_GATING: dict[str, str] = _not_gating(_AREAS)


def _static(site: str):
    """The value of a site that only source holds: a call literal, an environment, shell or gateway default."""
    rel = site.split(":", 1)[0]
    text = (REPO / rel).read_text(encoding="utf-8")
    if rel.endswith(".py"):
        found = _sites(text, rel)
    elif rel.endswith(".sh"):
        found = _shell_sites(text, rel)
    else:
        found = _gateway_sites(text, rel)
    if site not in found:
        raise ValueError(f"not a site: {site!r}")
    return found[site]


def _env_number(raw: str):
    """A shell variable's numeric value, None when it is unset or not a number."""
    if not re.fullmatch(r"-?\d+(\.\d*)?", raw.strip()):
        return None
    return float(raw) if "." in raw else int(raw)


def resolve(site: str):
    """The value a site names now: a module constant, a table entry, an argument or field default, or a literal in source."""
    m = _SITE.fullmatch(site)
    if m is None and re.fullmatch(r"scripts/[^/]+\.sh:\w+", site):
        # The script's ${VAR:-N} yields to VAR, so the registry does too. #704.
        got = _env_number(os.environ.get(site.split(":", 1)[1], ""))
        if got is not None:
            return got
    if m is None or m["name"] == "environ":
        return _static(site)
    got = importlib.import_module(m["rel"][:-3].replace("/", "."))
    try:
        for part in m["name"].split("."):
            got = getattr(got, part)
    except AttributeError:
        return _static(site)
    for key in re.findall(r"\[([\w.-]+)\]", m["keys"] or ""):
        got = got[key]
    if m["param"]:
        return _inspect.signature(got).parameters[m["param"]].default
    return got


def _numeric(node) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if isinstance(node, ast.UnaryOp):
        return _numeric(node.operand)
    if isinstance(node, ast.BinOp):
        return _num_or_ref(node.left) and _num_or_ref(node.right) and (_numeric(node.left) or _numeric(node.right))
    if isinstance(node, ast.Dict):
        return bool(node.values) and all(_num_or_ref(v) for v in node.values) and any(_numeric(v) for v in node.values)
    return False


def _num_or_ref(node) -> bool:
    return _numeric(node) or isinstance(node, (ast.Name, ast.Attribute))


def named_gating(name: str) -> bool:
    """Whether a constant, table key or environment variable name says it gates an outcome."""
    name = name.upper().strip("_")
    return bool(GATING_WORDS & set(name.split("_")) or name.endswith(GATING_SUFFIXES)
                or any(p in name for p in GATING_PHRASES))


def _param_gating(name: str) -> bool:
    return name in GATING_PARAMS or name.endswith("_s") or named_gating(name)


def _literal(node) -> bool:
    if isinstance(node, (ast.Tuple, ast.List)):
        return bool(node.elts) and all(_literal(e) for e in node.elts)
    if isinstance(node, ast.UnaryOp):
        return _literal(node.operand)
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def _dotted(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else ""
    return ""


def _table(rel: str, path: str, node) -> list[tuple[str, object]]:
    out = []
    for key, value in zip(node.keys, node.values):
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str) and re.fullmatch(r"[\w.-]+", key.value)):
            continue
        here = f"{path}[{key.value}]"
        if isinstance(value, ast.Dict):
            out += _table(rel, here, value)
        elif _literal(value):
            out.append((f"{rel}:{here}", value))
    return out


def _env_default(node) -> tuple[str, object] | None:
    """(VAR, default node) for os.environ.get(VAR, N), os.getenv(VAR, N), or either `or N`."""
    def env(call):
        while isinstance(call, ast.Call) and not _dotted(call.func).endswith(("environ.get", "getenv")):
            if len(call.args) != 1:
                return None
            call = call.args[0]
        if (isinstance(call, ast.Call) and call.args and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)):
            return call
        return None
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and len(node.values) == 2:
        call = env(node.values[0])
        return (call.args[0].value, node.values[1]) if call is not None else None
    if isinstance(node, ast.Call) and _dotted(node.func).endswith(("environ.get", "getenv")):
        call = env(node)
        if call is not None and len(call.args) == 2:
            return call.args[0].value, call.args[1]
    return None


def _number(node) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            float(node.value)
        except ValueError:
            return False
        return True
    return _literal(node)


def _value(node):
    got = ast.literal_eval(node)
    return float(got) if isinstance(got, str) else got


#: Methods whose first positional argument is a timeout: Popen/Event.wait, Thread/Process.join.
_POSITIONAL_TIMEOUT = ("wait", "join")


def _field(node) -> tuple[str, object] | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id, node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return node.target.id, node.value
    return None


def _scoped(rel: str, body, scope: str) -> list[tuple[str, object]]:
    out = []

    def visit(node, scope, in_class=False):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qual = f"{scope}.{node.name}" if scope else node.name
            a = node.args
            pos = a.posonlyargs + a.args
            pairs = list(zip(pos[len(pos) - len(a.defaults):], a.defaults)) + [
                (arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
            out.extend((f"{rel}:{qual}({arg.arg})", d) for arg, d in pairs if _param_gating(arg.arg) and _literal(d))
            for child in node.body:
                visit(child, qual)
            return
        if isinstance(node, ast.ClassDef):
            qual = f"{scope}.{node.name}" if scope else node.name
            for child in node.body:
                visit(child, qual, in_class=True)
            return
        field = _field(node) if in_class else None
        if field and _param_gating(field[0]) and _literal(field[1]):
            out.append((f"{rel}:{scope}.{field[0]}", field[1]))
        if isinstance(node, ast.Call):
            callee = _dotted(node.func) or "call"
            here = scope or "<module>"
            out.extend((f"{rel}:{here}->{callee}({kw.arg})", kw.value) for kw in node.keywords
                       if kw.arg and _param_gating(kw.arg) and _literal(kw.value))
            if (isinstance(node.func, ast.Attribute) and node.func.attr in _POSITIONAL_TIMEOUT and node.args
                    and _literal(node.args[0])):
                out.append((f"{rel}:{here}->{callee}(timeout)", node.args[0]))
        got = _env_default(node)
        if got and _number(got[1]):
            out.append((f"{rel}:environ({got[0]})", got[1]))
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    for stmt in body:
        visit(stmt, scope)
    return out


def _numbered(pairs) -> dict:
    """Each site once; a repeat of a site in the same file is a new site, `site#2`, so adding one is seen."""
    out, seen = {}, {}
    for site, value in pairs:
        seen[site] = seen.get(site, 0) + 1
        out[site if seen[site] == 1 else f"{site}#{seen[site]}"] = value
    return out


def _sites(text: str, rel: str) -> dict:
    out = []
    for stmt in ast.parse(text).body:
        name, value = _field(stmt) or (None, None)
        if name and _UPPER.fullmatch(name) and named_gating(name) and _numeric(value):
            out.append((f"{rel}:{name}", value))
        elif name and isinstance(value, ast.Dict):
            out += _table(rel, name, value)
        out += _scoped(rel, [stmt], "")
    return {site: _value(node) if _number(node) else None for site, node in _numbered(out).items()}


def gating(text: str, rel: str) -> list[str]:
    """Sites rel:NAME, rel:NAME[key], rel:func(param), rel:Class.field, rel:scope->callee(param), rel:environ(VAR), in source order."""
    return list(_sites(text, rel))


def _shell_sites(text: str, rel: str) -> dict:
    return _numbered((f"{rel}:{m[1]}", float(m[2]) if "." in m[2] else int(m[2]))
                     for m in _SHELL_DEFAULT.finditer(text))


def shell_defaults(text: str, rel: str) -> list[str]:
    """Sites rel:VAR of every numeric `${VAR:-N}` default in a shell script, whatever its name."""
    return list(_shell_sites(text, rel))


def _gateway_sites(text: str, rel: str) -> dict:
    import yaml
    data = yaml.safe_load(text)
    settings = data.get("litellm_settings") if isinstance(data, dict) else None
    out = {}

    def walk(d, prefix):
        for k, v in d.items():
            if isinstance(v, dict):
                walk(v, f"{prefix}.{k}")
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{rel}:{prefix}.{k}"] = v
    if isinstance(settings, dict):
        walk(settings, "litellm_settings")
    return out


def gateway_settings(text: str, rel: str) -> list[str]:
    """Sites rel:litellm_settings.path of every number the gateway's LiteLLM settings set."""
    return list(_gateway_sites(text, rel))


def _production(rel: str) -> bool:
    return rel.endswith(".py") and rel.startswith(("harness/", "evals/")) and not rel.startswith("evals/cases/")


def inventory(root) -> list[str]:
    """Every gating value in production Python, top-level scripts and gateway config under `root`, by site."""
    from harness import repo
    root = Path(root)
    out = []
    for path in repo.publishable(root):
        rel = path.relative_to(root).as_posix()
        if not path.is_file():
            continue
        if _production(rel):
            out += gating(path.read_text(encoding="utf-8", errors="replace"), rel)
        elif re.fullmatch(r"scripts/[^/]+\.sh", rel):
            out += shell_defaults(path.read_text(encoding="utf-8", errors="replace"), rel)
        elif re.fullmatch(r"gateway/[^/]+\.ya?ml", rel):
            out += gateway_settings(path.read_text(encoding="utf-8", errors="replace"), rel)
    return out


def registered() -> set[str]:
    return {s for k in KNOBS.values() for s in k.sites}


def not_gating(site: str) -> bool:
    """Whether NOT_GATING names this exact site."""
    return site in NOT_GATING


def unregistered(found) -> list[str]:
    known = registered()
    return [s for s in found if s not in known and not not_gating(s)]


def census(root) -> dict:
    """How many gating constants the registry covers and how many it does not."""
    found = inventory(root)
    known = registered()
    return {"found": found, "registered": sum(1 for s in found if s in known),
            "not_gating": sum(1 for s in found if not_gating(s)),
            "unregistered": len(unregistered(found))}


def limits() -> dict:
    """The `limit:` values this harness currently chooses, by predicate name; collect() gives each name one knob."""
    out = {}
    for k in KNOBS.values():
        if not k.limit or k.predicate != LIMIT:
            continue
        out[k.limit_name("")] = k.limit_value("")
        if "{lane}" in k.limit:
            for lane in k.lanes:
                out[k.limit_name(lane)] = k.limit_value(lane)
    return out


def limit_units() -> dict:
    """The unit each recorded limit name is in, lane-scoped names included (#752)."""
    return {name: k.unit for k in KNOBS.values() for name in _limit_names(k)}


def hit(name: str, value, unit: str) -> tuple:
    """(name, value) for an exception's `limit`, refused unless a knob records `name` in `unit` (#752)."""
    have = limit_units().get(name)
    if have is None:
        raise ValueError(f"{name!r} is no knob's limit")
    if have != unit:
        raise ValueError(f"limit {name!r} is in {have}, not {unit}")
    return name, value


def settings(lane: str, overrides: dict | None = None) -> dict:
    """The exam knobs an eval of `lane` runs at, by knob name: their defaults, or the values a run names."""
    overrides = dict(overrides or {})
    unknown = sorted(n for n in overrides if n not in KNOBS or KNOBS[n].receipt != "knobs")
    if unknown:
        raise ValueError(f"not a knob a run can set: {', '.join(unknown)}")
    return {k.name: overrides.get(k.name, k.default(lane)) for k in KNOBS.values()
            if k.receipt == "knobs" and lane in k.lanes}


def rebind(overrides: dict):
    """Set each override that has no runner attribute on its module for the duration; restore after."""
    import contextlib

    @contextlib.contextmanager
    def held():
        saved = []
        try:
            for name, value in overrides.items():
                k = KNOBS[name]
                if k.runner_attr:
                    continue
                m = _SITE.fullmatch(k.sites[0])
                if m is None or "." in m["name"] or m["keys"] or m["param"]:
                    raise ValueError(f"{name}: only a module constant can be rebound, not {k.sites[0]}")
                module = importlib.import_module(m["rel"][:-3].replace("/", "."))
                saved.append((module, m["name"], getattr(module, m["name"])))
                setattr(module, m["name"], value)
            yield
        finally:
            for module, attr, old in reversed(saved):
                setattr(module, attr, old)
    return held()


def apply(runner, overrides: dict) -> None:
    """Set the overrides a runner carries as attributes."""
    for name, value in overrides.items():
        attr = KNOBS[name].runner_attr
        if attr and hasattr(runner, attr):
            setattr(runner, attr, value)
