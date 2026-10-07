"""Rules that only a machine unlike the author's would notice being broken.

Everything here reads the SOURCE rather than running it. That is deliberate:
these are defects that cannot fail on macOS, so no amount of running the suite
there would catch one being reintroduced.
"""
import ast
import importlib.metadata
import re
import sys
import tomllib
from pathlib import Path

from tests.gauntlet import scanners

REPO = Path(__file__).resolve().parents[1]
#: The tests too. `open("scripts/env.sh").read()` in a test fails on
#: Windows for exactly the same reason the library code did.
PACKAGES = ("harness", "evals", "tests")

#: `Path.read_text(encoding="utf-8")` and `.write_text()` with no encoding use
#: `locale.getencoding()`. That is UTF-8 on macOS and cp1252 on a stock
#: Windows install, so a file holding any byte outside cp1252 raises
#: UnicodeDecodeError there and nowhere else.
_TEXT_IO = ("read_text", "write_text")


def _sources():
    for package in PACKAGES:
        yield from sorted((REPO / package).rglob("*.py"))


def test_no_text_file_is_read_or_written_without_an_explicit_encoding():
    """CAUGHT 17 FAILING TESTS ON WINDOWS AT ONCE.

    `charmap codec can't decode byte 0x9d` out of a YAML case file, a cached
    feed and a cloned candidate's source. The author's machine cannot produce
    this failure, which is the whole reason it is asserted against the source.
    """
    offenders = []
    for path in _sources():
        # Parsed, not grepped: the call may be spread over several lines, and a
        # line-wise check reported three already-fixed sites as offenders.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _TEXT_IO
                    and not any(kw.arg == "encoding" for kw in node.keywords)):
                offenders.append(
                    f"{path.relative_to(REPO)}:{node.lineno}: .{node.func.attr}()")
    assert not offenders, (
        "text I/O without an explicit encoding defaults to the locale codepage "
        "on Windows:\n  " + "\n  ".join(offenders))


#: `df -g` is a BSD flag. GNU coreutils -- Git Bash on Windows, and Linux --
#: answers "unknown option -- g", so the function reads empty, every candidate
#: is judged unusable, and env.sh reports "no writable location with 0GB free".
#: That reads as a machine with no disk rather than as a wrong flag.
#: `df -Pk` forces 1024-byte blocks on both.
_BSD_DF = re.compile(r"df\s+-[A-Za-z]*g")


def test_no_script_uses_a_bsd_only_df_flag():
    offenders = []
    for path in sorted((REPO / "scripts").glob("*.sh")):
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            if _BSD_DF.search(line):
                offenders.append(
                    f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    assert not offenders, (
        "df -g is BSD-only; use `df -Pk` and divide by 1048576 -- "
        + "; ".join(offenders))


def test_no_posix_only_primitive_is_used_without_a_platform_guard():
    """#552: harness/vllm.py stopped its child with os.killpg, which Windows does not have."""
    offenders = []
    for path in _sources():
        offenders += scanners.posix_primitives(path.read_text(encoding="utf-8"),
                                               path.relative_to(REPO).as_posix())
    assert not offenders, "a POSIX-only primitive with no platform guard:\n  " + "\n  ".join(offenders)


# The groups `make test` syncs on every CI platform: uv's default group plus the Makefile's --group flags.
def _test_groups():
    make = (REPO / "Makefile").read_text(encoding="utf-8")
    recipe = re.search(r"^test:.*\n((?:\t.*\n)+)", make, re.M).group(1)
    return {"dev", *re.findall(r"--group\s+(\S+)", recipe)}


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements():
    """(distribution, marker, group) for every requirement pyproject declares; group None is [project]."""
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    rows = [(r, None) for r in data["project"]["dependencies"]]
    rows += [(r, g) for g, reqs in data.get("dependency-groups", {}).items() for r in reqs if isinstance(r, str)]
    out = []
    for req, group in rows:
        spec, _, marker = req.partition(";")
        out.append((_norm(re.match(r"[A-Za-z0-9_.\-]+", spec.strip()).group(0)), marker.strip(), group))
    return out


def _third_party(top):
    return not (top in sys.stdlib_module_names or top in ("harness", "evals", "tests", "__future__")
                or (REPO / "tests" / f"{top}.py").exists() or (REPO / "tests" / top).is_dir())


def _dists(top):
    # Not installed here: assume the distribution shares the module's name.
    return {_norm(d) for d in importlib.metadata.packages_distributions().get(top, ())} or {_norm(top)}


def _closure(roots):
    """`roots` and what they require unconditionally; a marked requirement may be absent somewhere."""
    seen, todo = set(), list(roots)
    while todo:
        dist = todo.pop()
        if dist in seen:
            continue
        seen.add(dist)
        try:
            reqs = importlib.metadata.requires(dist) or []
        except importlib.metadata.PackageNotFoundError:
            continue
        todo += [_norm(re.match(r"[A-Za-z0-9_.\-]+", r).group(0)) for r in reqs if ";" not in r]
    return seen


def _skip_covered(text, rel, requirements):
    """Distributions a file's module-level importorskip covers: the skipped one's whole group."""
    skipped = set().union(*(_dists(m) for m in scanners.module_skips(text, rel)))
    groups = {g for d, _, g in requirements if d in skipped and g}
    return skipped | {d for d, _, g in requirements if g in groups}


def test_every_module_a_test_imports_is_installed_on_every_platform():
    """#551: tests/test_loop_circuit.py imported huggingface_hub, which only mlx-lm (darwin) pulled in."""
    groups = _test_groups()
    requirements = _requirements()
    everywhere = _closure({d for d, marker, g in requirements if not marker and (g is None or g in groups)})
    offenders = []
    for path in sorted((REPO / "tests").rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        text = path.read_text(encoding="utf-8")
        covered = everywhere | _skip_covered(text, rel, requirements)
        offenders += [f"{rel}:{line}: {top}" for line, top in scanners.unguarded_imports(text, rel)
                      if _third_party(top) and not _dists(top) & covered]
    assert not offenders, (
        "a test imports a module no unmarked requirement in [project] or the groups `make test` syncs "
        f"({', '.join(sorted(groups))}) provides, so Linux or Windows CI may not have it; declare it, "
        "or pytest.importorskip it with a reason:\n  " + "\n  ".join(offenders))
