"""Whether a runner venv holds exactly what its script resolves to: its pins and their dependencies. #1032.

    uv run python -m harness.venv_drift   print each runner venv's drift
"""
from __future__ import annotations

import re
import sys
from email.parser import HeaderParser
from pathlib import Path

#: The script's per-platform branch: Darwin pins on the Mac, the CUDA index elsewhere.
_UNAME = re.compile(r'^\s*if \[ "\$\(uname -s\)" = "Darwin" \]; then\n(.*?)^\s*else\n(.*?)^\s*fi\b', re.M | re.S)


def _this_platform(text: str) -> str:
    darwin = sys.platform == "darwin"
    return _UNAME.sub(lambda m: m.group(1) if darwin else m.group(2), text)


def pins(venv: str, repo: Path) -> dict[str, str]:
    """Canonical name -> the pin `venv`'s script installs on this platform, each `$X_PIN` read from scripts/versions.sh."""
    from harness import runner_gaps
    script, *arrays = runner_gaps.VENV_SCRIPTS[venv]
    try:
        text = _this_platform((repo / script).read_text(encoding="utf-8"))
        versions = (repo / "scripts" / "versions.sh").read_text(encoding="utf-8")
    except OSError:
        return {}
    values = dict(re.findall(r'^([A-Z0-9_]+)="([^"]*)"', versions, re.M))
    out = {}
    for array in arrays:
        for word in runner_gaps._bash_values(text, array):
            ref = re.fullmatch(r"\$\{?([A-Z0-9_]+)\}?", word)
            value = values.get(ref.group(1), "") if ref else word
            name = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", value)
            if name and not value.startswith(("-", "http")):
                out[runner_gaps._canonical(name.group(0))] = value
    return out


def _site(root: Path) -> list[Path]:
    return [p for p in (*root.glob("lib/python*/site-packages"), root / "Lib" / "site-packages") if p.is_dir()]


def _python_version(root: Path) -> str:
    try:
        cfg = (root / "pyvenv.cfg").read_text(encoding="utf-8")
    except OSError:
        cfg = ""
    got = re.search(r"^version(?:_info)?\s*=\s*(\d+\.\d+(?:\.\d+)?)", cfg, re.M)
    if got:
        return got.group(1)
    lib = next(iter(root.glob("lib/python3.*")), None)
    return lib.name.removeprefix("python") if lib else f"{sys.version_info.major}.{sys.version_info.minor}"


def installed(root: Path) -> dict[str, tuple[str, list[str]]]:
    """Canonical name -> (version, Requires-Dist lines) for each distribution in the venv, read from METADATA."""
    from harness import runner_gaps
    out = {}
    for site in _site(root):
        for info in site.glob("*.dist-info"):
            try:
                meta = HeaderParser().parsestr((info / "METADATA").read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if meta.get("Name"):
                out[runner_gaps._canonical(meta["Name"])] = (meta.get("Version", ""), meta.get_all("Requires-Dist") or [])
    return out


def _closure(wanted: dict[str, str], have: dict, python: str) -> set[str]:
    from packaging.requirements import InvalidRequirement, Requirement
    from harness import runner_gaps
    full = python if python.count(".") == 2 else python + ".0"
    env = {"sys_platform": sys.platform, "python_version": ".".join(python.split(".")[:2]),
           "python_full_version": full}
    seen: set[str] = set()
    todo = [(name, frozenset()) for name in wanted]
    while todo:
        name, extras = todo.pop()
        if name not in have or (name, extras) in seen:
            continue
        seen.add((name, extras))
        for text in have[name][1]:
            try:
                req = Requirement(text)
            except InvalidRequirement:
                continue
            if req.marker is None or any(req.marker.evaluate({**env, "extra": e}) for e in ("", *extras)):
                todo.append((runner_gaps._canonical(req.name), frozenset(req.extras)))
    return {name for name, _ in seen}


def drift(venv: str, repo: Path, root: Path | None = None) -> dict[str, list[str]]:
    """{extra, missing, version}: installed dists no pin resolves to, pins not installed, pins installed off-version."""
    from packaging.requirements import Requirement
    from harness import runner_gaps
    root = root or runner_gaps.venv_path(venv)
    wanted = pins(venv, repo)
    have = installed(root)
    reached = _closure(wanted, have, _python_version(root))
    off = []
    for name, pin in sorted(wanted.items()):
        if name in have and not Requirement(pin).specifier.contains(have[name][0], prereleases=True):
            off.append(f"{name} {have[name][0]} (pins {pin})")
    return {"extra": [f"{n} {have[n][0]}" for n in sorted(set(have) - reached)],
            "missing": sorted(pin for name, pin in wanted.items() if name not in have),
            "version": off}


def report(repo: Path) -> list[str]:
    """One line per built runner venv whose contents differ from what its script resolves to."""
    from harness import runner_gaps
    lines = []
    for venv in runner_gaps.VENV_SCRIPTS:
        root = runner_gaps.venv_path(venv)
        if not _site(root):
            continue
        got = drift(venv, repo, root)
        parts = [f"{k} {', '.join(v)}" for k, v in got.items() if v]
        if parts:
            lines.append(f"{venv}: " + "; ".join(parts))
    return lines


if __name__ == "__main__":
    from harness import paths
    print("\n".join(report(paths.runs_elsewhere() or paths.REPO)) or "every runner venv matches its script")
