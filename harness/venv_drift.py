"""Whether a runner venv holds exactly what its script resolves to: its pins and their dependencies. #1032.

    uv run python -m harness.venv_drift   print each runner venv's drift
"""
from __future__ import annotations

import json
import platform
import re
import sys
from email.parser import HeaderParser
from pathlib import Path

#: The script's per-platform branch: Darwin (or Apple Silicon) pins on the Mac, the CUDA index elsewhere.
_UNAME = re.compile(r'^\s*if \[ "\$\(uname -s\)" = "Darwin" \]( && \[ "\$\(uname -m\)" = "arm64" \])?; then\n'
                    r'(.*?)^\s*else\n(.*?)^\s*fi\b', re.M | re.S)


def _this_platform(text: str) -> str:
    def branch(m):
        mac = sys.platform == "darwin" and (not m.group(1) or platform.machine() == "arm64")
        return m.group(2) if mac else m.group(3)
    return _UNAME.sub(branch, text)


def _words(venv: str, repo: Path) -> list[str]:
    """Each word of `venv`'s script pin arrays on this platform, a `$X_PIN` replaced by its value in scripts/versions.sh."""
    from harness import runner_gaps
    script, *arrays = runner_gaps.VENV_SCRIPTS[venv]
    try:
        text = _this_platform((repo / script).read_text(encoding="utf-8"))
        versions = (repo / "scripts" / "versions.sh").read_text(encoding="utf-8")
    except OSError:
        return []
    values = dict(re.findall(r'^([A-Z0-9_]+)="([^"]*)"', versions, re.M))
    out = []
    for array in arrays:
        for word in runner_gaps._bash_values(text, array):
            ref = re.fullmatch(r"\$\{?([A-Z0-9_]+)\}?", word)
            out.append(values.get(ref.group(1), "") if ref else word)
    return out


def pins(venv: str, repo: Path) -> dict[str, str]:
    """Canonical name -> the pin `venv`'s script installs on this platform."""
    from harness import runner_gaps
    out = {}
    for value in _words(venv, repo):
        name = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", value)
        if name and not value.startswith(("-", "http")):
            out[runner_gaps._canonical(name.group(0))] = value
    return out


def checkouts(venv: str, repo: Path) -> list[str]:
    """The words of `venv`'s pin arrays that install a local checkout by its path. #1037."""
    return [w for w in _words(venv, repo) if w.startswith(("$", "/", "."))]


def from_checkout(root: Path) -> set[str]:
    """Canonical names of the venv's dists installed from a local directory, per their direct_url.json. #1037."""
    from harness import runner_gaps
    out = set()
    for site in _site(root):
        for info in site.glob("*.dist-info"):
            try:
                url = json.loads((info / "direct_url.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(url, dict) and "dir_info" in url:
                out.add(runner_gaps._canonical(info.name[:-len(".dist-info")].rpartition("-")[0]))
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


def _closure(wanted, have: dict, python: str) -> set[str]:
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
    # A local checkout's dist is no pin, so the closure starts from it too. #1037.
    local = checkouts(venv, repo)
    built = from_checkout(root) if local else set()
    reached = _closure([*wanted, *built], have, _python_version(root))
    off = []
    for name, pin in sorted(wanted.items()):
        if name in have and not Requirement(pin).specifier.contains(have[name][0], prereleases=True):
            off.append(f"{name} {have[name][0]} (pins {pin})")
    return {"extra": [f"{n} {have[n][0]}" for n in sorted(set(have) - reached)],
            "missing": sorted([pin for name, pin in wanted.items() if name not in have] + ([] if built else local)),
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
