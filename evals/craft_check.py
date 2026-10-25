"""The craft exam's checker: named requirements over a document the app reported, and a render difference (#1209)."""
from __future__ import annotations

import math
from pathlib import Path

#: The requirement kinds; each requirement names exactly one.
KINDS = ("count", "node", "aligned", "distributed", "ordered", "grouped", "connects", "inside", "file")
#: Bytes of an exported file a requirement's magic is looked for in.
MAGIC_SPAN = 512
EDGES = {"left": lambda n: n["x"], "right": lambda n: n["x"] + n["w"], "center": lambda n: n["x"] + n["w"] / 2,
         "top": lambda n: n["y"], "bottom": lambda n: n["y"] + n["h"], "middle": lambda n: n["y"] + n["h"] / 2}
AXES = ("x", "y")


def validate(requirements) -> None:
    """Refuse a requirement list the checker could only answer vacuously or ambiguously."""
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("assert.craft.requirements must be a non-empty list")
    seen = set()
    for r in requirements:
        if not isinstance(r, dict) or not r.get("id"):
            raise ValueError(f"every requirement needs an id: {r!r}")
        if r["id"] in seen:
            raise ValueError(f"requirement {r['id']!r} is named twice")
        seen.add(r["id"])
        kinds = [k for k in KINDS if k in r]
        if len(kinds) != 1:
            raise ValueError(f"requirement {r['id']!r} must name one of {', '.join(KINDS)}; got {kinds or 'none'}")
        kind = kinds[0]
        if kind == "count" and not isinstance(r.get("equals"), int):
            raise ValueError(f"requirement {r['id']!r}: a count needs an integer equals")
        if kind == "node" and not (r.get("expect") or r.get("aspect")):
            raise ValueError(f"requirement {r['id']!r}: a node requirement needs expect or aspect")
        if kind == "aligned" and r[kind].get("edge") not in EDGES:
            raise ValueError(f"requirement {r['id']!r}: edge must be one of {', '.join(EDGES)}")
        if kind in ("distributed", "ordered") and r[kind].get("axis") not in AXES:
            raise ValueError(f"requirement {r['id']!r}: axis must be x or y")
        if kind in ("aligned", "distributed", "ordered") and len(r[kind].get("names") or []) < 2:
            raise ValueError(f"requirement {r['id']!r}: {kind} needs at least two names")
        if kind == "file":
            rel = str(r[kind].get("path") or "")
            parts = rel.replace("\\", "/").split("/")
            if not rel or rel.startswith(("/", "~")) or ":" in rel or ".." in parts or not r[kind].get("magic"):
                raise ValueError(f"requirement {r['id']!r}: a file needs a magic and a path inside the working folder")


def field(node: dict, path: str):
    got = node
    for part in path.split("."):
        if not isinstance(got, dict) or part not in got:
            return None
        got = got[part]
    return got


def same(want, got, tolerance: float) -> bool:
    if isinstance(want, bool) or isinstance(got, bool):
        return want == got
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return abs(float(want) - float(got)) <= tolerance
    if isinstance(want, str) and isinstance(got, str) and want.startswith("#"):
        return want.lower() == got.lower()
    return want == got


def matching(nodes: list, select: dict) -> list:
    return [n for n in nodes if all(field(n, k) == v for k, v in select.items())]


def _one(nodes: list, select: dict):
    """(node, why): the one node a selector names, or the reason there is not one."""
    got = matching(nodes, select)
    if len(got) == 1:
        return got[0], ""
    return None, f"{len(got)} nodes match {select}" if got else f"no node matches {select}"


def _named(nodes: list, names: list) -> tuple[list, str]:
    out = []
    for name in names:
        n, why = _one(nodes, {"name": name})
        if n is None:
            return [], why
        out.append(n)
    return out, ""


def _geometric(n: dict) -> bool:
    return all(isinstance(n.get(k), (int, float)) for k in ("x", "y", "w", "h"))


def _gap_to(point, n: dict) -> float:
    """Distance from a point to a node's box; 0 inside it."""
    px, py = point
    dx = max(n["x"] - px, 0.0, px - (n["x"] + n["w"]))
    dy = max(n["y"] - py, 0.0, py - (n["y"] + n["h"]))
    return math.hypot(dx, dy)


def _ancestors(nodes: list, n: dict) -> list:
    by_id = {m["id"]: m for m in nodes}
    out, seen, at = [], set(), n.get("parent")
    while at is not None and at in by_id and at not in seen:
        seen.add(at)
        out.append(at)
        at = by_id[at].get("parent")
    return out


def _file(spec: dict, root: Path | None) -> tuple[bool, str]:
    if root is None:
        return False, "no working folder to look in"
    path = Path(root) / spec["path"]
    if not path.is_file():
        return False, f"{spec['path']} was not written"
    with open(path, "rb") as f:
        head = f.read(MAGIC_SPAN)
    ok = spec["magic"].encode("utf-8") in head
    return ok, f"{spec['path']}: {len(head)}+ bytes" + ("" if ok else f", no {spec['magic']!r} in its first {MAGIC_SPAN}")


def _requirement(r: dict, nodes: list, tol: float, root: Path | None = None) -> tuple[bool, str]:
    if "file" in r:
        return _file(r["file"], root)
    if "count" in r:
        n = len(matching(nodes, r["count"]))
        return n == r["equals"], f"{n} nodes match {r['count']}, want {r['equals']}"
    if "node" in r:
        n, why = _one(nodes, r["node"])
        if n is None:
            return False, why
        for path, want in (r.get("expect") or {}).items():
            got = field(n, path)
            if not same(want, got, tol):
                return False, f"{path} is {got!r}, want {want!r}"
        if r.get("aspect"):
            aw, ah = r["aspect"]
            if not _geometric(n) or not n["h"] or abs(n["w"] / n["h"] - aw / ah) * n["h"] > tol:
                return False, f"{n.get('w')}x{n.get('h')} is not {aw}:{ah}"
        return True, "as specified"
    if "aligned" in r:
        got, why = _named(nodes, r["aligned"]["names"])
        if not got or not all(_geometric(n) for n in got):
            return False, why or "a named node has no geometry"
        at = [EDGES[r["aligned"]["edge"]](n) for n in got]
        spread = max(at) - min(at)
        return spread <= tol, f"{r['aligned']['edge']} edges spread {spread:g}"
    if "distributed" in r:
        got, why = _named(nodes, r["distributed"]["names"])
        if not got or not all(_geometric(n) for n in got):
            return False, why or "a named node has no geometry"
        axis = r["distributed"]["axis"]
        size = "w" if axis == "x" else "h"
        got.sort(key=lambda n: n[axis])
        gaps = [b[axis] - (a[axis] + a[size]) for a, b in zip(got, got[1:])]
        spread = max(gaps) - min(gaps)
        return spread <= tol, f"gaps {[round(g, 2) for g in gaps]} spread {spread:g}"
    if "ordered" in r:
        got, why = _named(nodes, r["ordered"]["names"])
        if not got or not all(_geometric(n) for n in got):
            return False, why or "a named node has no geometry"
        axis = r["ordered"]["axis"]
        at = [n[axis] for n in got]
        ok = all(a < b for a, b in zip(at, at[1:]))
        return ok, f"{axis} positions {[round(v, 2) for v in at]}"
    if "grouped" in r:
        group, why = _one(nodes, {"name": r["grouped"]["group"]})
        if group is None:
            return False, why
        got, why = _named(nodes, r["grouped"]["members"])
        if not got:
            return False, why
        outside = [n["name"] for n in got if group["id"] not in _ancestors(nodes, n)]
        return not outside, f"not in {group['name']}: {', '.join(outside)}" if outside else "grouped"
    if "connects" in r:
        spec = r["connects"]
        line, why = _one(nodes, {"name": spec["line"]})
        if line is None:
            return False, why
        ends, why = _named(nodes, [spec["from"], spec["to"]])
        points = line.get("points") or []
        if not ends or len(points) < 2:
            return False, why or f"{spec['line']} has no end points"
        gaps = (_gap_to(points[0], ends[0]), _gap_to(points[-1], ends[1]))
        return max(gaps) <= tol, f"ends {gaps[0]:g} and {gaps[1]:g} from their boxes"
    inner, why = _one(nodes, {"name": r["inside"]["inner"]})
    outer, why2 = _one(nodes, {"name": r["inside"]["outer"]})
    if inner is None or outer is None:
        return False, why or why2
    if not (_geometric(inner) and _geometric(outer)):
        return False, "a named node has no geometry"
    over = max(outer["x"] - inner["x"], outer["y"] - inner["y"],
               inner["x"] + inner["w"] - outer["x"] - outer["w"], inner["y"] + inner["h"] - outer["y"] - outer["h"])
    return over <= tol, f"{inner['name']} overhangs {outer['name']} by {max(over, 0):g}"


def check(requirements: list, nodes: list, tolerance: float, root: Path | None = None) -> dict:
    """Each requirement's pass and why, in order, and whether all passed; file requirements look in `root`."""
    out = []
    for r in requirements:
        try:
            ok, detail = _requirement(r, nodes, tolerance, root)
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            ok, detail = False, f"unreadable document: {type(exc).__name__}: {exc}"
        out.append({"id": r["id"], "passed": bool(ok), "detail": detail})
    met = sum(1 for r in out if r["passed"])
    return {"passed": bool(out) and met == len(out), "met": met, "total": len(out), "requirements": out}


def render_difference(a: Path, b: Path) -> float:
    """Mean absolute RGB difference of two renders on white, 0 to 1; 1 when their sizes differ."""
    from PIL import Image, ImageChops, ImageStat

    def flat(p):
        with Image.open(p) as im:
            rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(bg, rgba).convert("RGB")

    x, y = flat(a), flat(b)
    if x.size != y.size:
        return 1.0
    means = ImageStat.Stat(ImageChops.difference(x, y)).mean
    return round(sum(means) / (len(means) * 255.0), 6)
