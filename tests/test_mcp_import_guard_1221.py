"""A test reaches harness.mcp_server only through importorskip, so the litellm overlay's mcp 1 skips it instead of failing collection. #1221."""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MCP_ONLY = ("mcp", "harness.mcp_server")


def _mcp_only(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in MCP_ONLY)


def unguarded(text: str, rel: str) -> list[str]:
    """Module-level imports of an mcp-only module, and importorskip probes of the bare mcp package."""
    tree = ast.parse(text, rel)
    found = []
    top = [n for stmt in tree.body for n in ast.walk(stmt)
           if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    for n in top:
        if isinstance(n, ast.Import):
            found += [f"{rel}:{n.lineno}: imports {a.name} at module level" for a in n.names if _mcp_only(a.name)]
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            names = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
            if any(_mcp_only(x) for x in names):
                found.append(f"{rel}:{n.lineno}: imports from {n.module} at module level")
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "importorskip"
                and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "mcp"):
            found.append(f"{rel}:{n.lineno}: importorskip('mcp') passes under mcp 1; probe harness.mcp_server")
    return found


def test_no_test_reaches_harness_mcp_server_but_through_importorskip():
    found = []
    for path in sorted((REPO / "tests").rglob("*.py")):
        found += unguarded(path.read_text(encoding="utf-8"), path.relative_to(REPO).as_posix())
    assert not found, "\n".join(found)


@pytest.mark.parametrize("text, flagged", [
    ("from harness import mcp_peers, mcp_server\n", True),
    ("import harness.mcp_server as s\n", True),
    ("from mcp.server.mcpserver import MCPServer\n", True),
    ("import pytest\npytest.importorskip('mcp')\n", True),
    ("import pytest\nmcp_server = pytest.importorskip('harness.mcp_server')\n", False),
    ("def test_x():\n    from harness import mcp_server\n", False),
    ("from harness import mcp_peers\n", False),
])
def test_the_scan_flags_a_planted_unguarded_import(text, flagged):
    assert bool(unguarded(text, "tests/test_planted.py")) is flagged


def _collect(tmp_path, body):
    """Run pytest on one planted file with a fake mcp 1 (no mcp.server.mcpserver) ahead of the real one."""
    fake = tmp_path / "fake" / "mcp" / "server"
    fake.mkdir(parents=True, exist_ok=True)
    (fake.parent / "__init__.py").write_text("", encoding="utf-8")
    (fake / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "test_planted.py").write_text(body, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path / "fake"), str(REPO)])
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=",
                           "-p", "no:randomly", "test_planted.py"],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)


def test_under_mcp_1_a_guarded_file_skips_and_an_unguarded_one_fails_collection(tmp_path):
    guarded = _collect(tmp_path, "import pytest\nmcp_server = pytest.importorskip('harness.mcp_server')\n\n"
                                 "def test_x():\n    pass\n")
    # 5: a module skipped at collection leaves no test to run, which is not an error
    assert guarded.returncode == 5 and "1 skipped" in guarded.stdout, guarded.stdout + guarded.stderr
    assert "error" not in guarded.stdout.lower(), guarded.stdout
    bare = _collect(tmp_path, "from harness import mcp_server\n\ndef test_x():\n    pass\n")
    assert bare.returncode == 2 and "mcp.server.mcpserver" in bare.stdout, bare.stdout + bare.stderr


def test_the_mcp_group_floor_is_a_version_harness_mcp_server_can_import():
    import tomllib
    group = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["dependency-groups"]["mcp"]
    assert any(r.replace(" ", "").startswith("mcp>=2") for r in group), group
