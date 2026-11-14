"""with-gpu-lock runs on system python3; on a Postgres store it must re-run under a venv with psycopg. #1586."""
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness import exclusive, store

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "scripts" / "with-gpu-lock"
POSIX = pytest.mark.skipif(sys.platform == "win32", reason="fake interpreters are sh scripts")


@pytest.fixture
def postgres_home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    monkeypatch.delenv(store.BACKEND_ENV, raising=False)
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.setenv("LH_DEPLOY", str(tmp_path / "deploy"))
    (tmp_path / store.MARKER).write_text(json.dumps({"backend": "postgres"}), encoding="utf-8")
    return tmp_path


def _no_psycopg(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)


def _venv(root: Path) -> Path:
    python = exclusive._venv_python(root)
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("", encoding="utf-8")
    return python


def test_a_sqlite_store_keeps_this_interpreter(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    monkeypatch.delenv(store.BACKEND_ENV, raising=False)
    _no_psycopg(monkeypatch)
    assert exclusive.store_python(tmp_path, can_import=lambda p: True) is None


def test_on_postgres_without_psycopg_the_repo_venv_is_chosen(postgres_home, monkeypatch):
    _no_psycopg(monkeypatch)
    repo = postgres_home / "repo"
    python = _venv(repo)
    assert exclusive.store_python(repo, can_import=lambda p: True) == str(python)


def test_the_deploy_venv_is_next_when_the_repo_venv_lacks_psycopg(postgres_home, monkeypatch):
    _no_psycopg(monkeypatch)
    repo = postgres_home / "repo"
    _venv(repo)
    deploy = _venv(postgres_home / "deploy")
    monkeypatch.setattr(exclusive.paths, "deploy_checkout", lambda: postgres_home / "deploy")
    assert exclusive.store_python(repo, can_import=lambda p: p == deploy) == str(deploy)


def test_no_interpreter_that_can_open_the_store_refuses_naming_each(postgres_home, monkeypatch):
    _no_psycopg(monkeypatch)
    repo = postgres_home / "repo"
    python = _venv(repo)
    with pytest.raises(RuntimeError) as got:
        exclusive.store_python(repo, can_import=lambda p: False)
    assert sys.executable in str(got.value) and str(python) in str(got.value)
    assert "psycopg" in str(got.value)


def test_a_nested_holder_needs_no_store(postgres_home, monkeypatch):
    _no_psycopg(monkeypatch)
    monkeypatch.setenv(exclusive.HELD_ENV, "1")
    assert exclusive.store_python(postgres_home, can_import=lambda p: False) is None


def _fake_repo(tmp_path: Path) -> Path:
    """The helper copied beside a link to the real harness, so its venv is one the test controls."""
    fake = tmp_path / "fake-repo"
    (fake / "scripts").mkdir(parents=True)
    shutil.copy2(HELPER, fake / "scripts" / "with-gpu-lock")
    (fake / "harness").symlink_to(REPO / "harness", target_is_directory=True)
    return fake


def _interpreter(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _run(fake: Path, *cmd: str):
    # -S drops site-packages, so this interpreter cannot import psycopg, as system python3 cannot.
    return subprocess.run([sys.executable, "-S", str(fake / "scripts" / "with-gpu-lock"), *cmd],
                          capture_output=True, text=True, timeout=60)


@POSIX
def test_the_helper_refuses_naming_the_interpreter_when_none_can_open_the_store(postgres_home):
    fake = _fake_repo(postgres_home)
    venv = _interpreter(fake / ".venv" / "bin" / "python", "exit 1\n")
    got = _run(fake, "true")
    assert got.returncode != 0
    assert sys.executable in got.stderr and str(venv) in got.stderr, got.stderr


@POSIX
def test_the_helper_reruns_itself_under_the_venv_that_has_psycopg(postgres_home):
    fake = _fake_repo(postgres_home)
    seen = postgres_home / "argv"
    _interpreter(fake / ".venv" / "bin" / "python",
                 f'case "$*" in *"import psycopg"*) exit 0;; esac\necho "$@" > {seen}\n')
    got = _run(fake, "true", "x")
    assert got.returncode == 0, got.stderr
    assert seen.read_text(encoding="utf-8").split() == ["-I", str(fake / "scripts" / "with-gpu-lock"), "true", "x"]


@POSIX
@pytest.mark.postgres
def test_under_the_venv_interpreter_the_batch_lease_is_taken(tmp_path, monkeypatch):
    monkeypatch.setenv(store.BACKEND_ENV, "postgres")
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    fake = _fake_repo(tmp_path)
    _interpreter(fake / ".venv" / "bin" / "python", f'exec {sys.executable} "$@"\n')
    count = (f"import sys; sys.path.insert(0, {str(REPO)!r}); "
             "from harness import batch, lease, memory_store as ms; c = ms.connect(); "
             "print(c.execute('SELECT count(*) FROM meta WHERE key LIKE ?', "
             "(lease.PREFIX + batch.PREFIX + '%',)).fetchone()[0])")
    got = _run(fake, sys.executable, "-c", count)
    assert got.returncode == 0, got.stderr
    assert "no batch lease" not in got.stderr
    assert int(got.stdout.strip()) >= 1


# ---- every entry point that runs on system python3 and reaches the store re-runs under a venv ----

SYSTEM_SHEBANG = re.compile(r"^#!\s*(/usr/bin/env\s+python3|/usr/bin/python3)\s*$")
SH_PYTHON3 = re.compile(r'^\s*python3\b[^\n#]*?"\$REPO/([\w/.-]+\.py)"', re.M)
STORE = {"harness/store.py", "harness/memory_store/__init__.py"}


def system_python_entry_points() -> set[str]:
    out = set()
    for path in (REPO / "scripts").iterdir():
        if path.is_file():
            try:
                first = path.read_text(encoding="utf-8").split("\n", 1)[0]
            except (UnicodeDecodeError, OSError):
                continue
            if SYSTEM_SHEBANG.match(first):
                out.add(path.relative_to(REPO).as_posix())
            if path.suffix == ".sh":
                out |= set(SH_PYTHON3.findall(path.read_text(encoding="utf-8")))
    return out


def _module_file(dotted: str) -> str | None:
    base = REPO / dotted.replace(".", "/")
    for cand in (base.with_suffix(".py"), base / "__init__.py"):
        if cand.is_file():
            return cand.relative_to(REPO).as_posix()
    return None


def _imports(rel: str) -> set[str]:
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    package = rel.rsplit("/", 1)[0].replace("/", ".")
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                parts = package.split(".")
                mod = ".".join(parts[:len(parts) - node.level + 1] + ([mod] if mod else []))
            names = [mod] + [f"{mod}.{a.name}" for a in node.names]
        else:
            continue
        for name in names:
            if name.split(".")[0] in ("harness", "evals") and (f := _module_file(name)):
                out.add(f)
    return out


def reaches_store(rel: str) -> bool:
    seen, todo = set(), [rel]
    while todo:
        cur = todo.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if cur in STORE:
            return True
        todo += _imports(cur) - seen
    return False


def test_with_gpu_lock_is_found_as_a_system_python_entry_point_that_reaches_the_store():
    assert "scripts/with-gpu-lock" in system_python_entry_points()
    assert reaches_store("scripts/with-gpu-lock")


#: Imports the store's code but never opens it: registry cards over HTTP; the live-home gate reads only paths (#2008).
NEVER_OPENS = {"scripts/record_fixtures.py", "harness/live_gate.py"}


def test_every_system_python_entry_point_that_reaches_the_store_reruns_under_a_venv():
    stranded = [rel for rel in sorted(system_python_entry_points())
                if reaches_store(rel) and rel not in NEVER_OPENS
                and "store_python(" not in (REPO / rel).read_text(encoding="utf-8")]
    assert stranded == [], f"run on system python3, reach the store, never re-run under a venv: {stranded}"


def test_an_entry_point_excused_as_never_opening_the_store_still_never_connects():
    for rel in NEVER_OPENS:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert reaches_store(rel), f"{rel} no longer reaches the store; drop it from NEVER_OPENS"
        assert "connect(" not in text and "open_ro(" not in text, rel
