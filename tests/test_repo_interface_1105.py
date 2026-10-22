"""The tests-call block also names the MCP tools, CLI options and environment variables a test asks for by string. #1105."""
import subprocess

from evals import interface
from evals.importers import history
from tests.test_repo_interface_1103 import _git, _write

CLI = ("import argparse\nimport os\n\n\ndef main(argv):\n    p = argparse.ArgumentParser()\n"
       "    p.add_argument('--old')\n    p.add_argument('--out')\n    os.environ.get('PKG_OLD_VAR')\n")
SERVER = "def register(mcp):\n    @mcp.tool()\n    def old_tool(a):\n        return a\n"
BASE = {"pkg/__init__.py": "", "pkg/cli.py": CLI, "pkg/server.py": SERVER, "README.md": "--readme-flag\n"}
FIX = {"pkg/cli.py": CLI + ("    q = argparse.ArgumentParser()\n    q.add_argument('--fresh-flag')\n"
                            "    q.add_argument('--out')\n    os.environ.get('PKG_NEW_VAR')\n"
                            "    q.add_argument('--unused-flag')\n    os.environ.get('PKG_UNUSED_VAR')\n"
                            "    os.environ.get('lower_name')\n    print('PKG_PRINTED')\n"
                            "    return os.environ['PKG_SUB_VAR'], 'PKG_NOT_READ'\n"),
       "pkg/script.txt": "p.add_argument('--txt-flag')\n",
       "pkg/server.py": SERVER + ("\n    @mcp.tool()\n    def new_tool(x: int = 1) -> str:\n        return ''\n\n"
                                  "    def helper_not_a_tool():\n        pass\n\n"
                                  "    @mcp.tool()\n    def unused_tool():\n        pass\n"),
       "README.md": "--readme-flag\n--doc-only-flag\n",
       "tests/test_cli.py": (
           "from pkg.cli import main\n\n\ndef test_flags_and_tools(monkeypatch, tools):\n"
           "    monkeypatch.setenv('PKG_NEW_VAR', '1')\n    assert 'environ[\\'PKG_SUB_VAR\\']' in SOURCE\n"
           "    monkeypatch.setenv('PKG_OLD_VAR', '1')\n    monkeypatch.setenv('PKG_NOT_READ', '1')\n"
           "    assert 'PKG_PRINTED' and 'lower_name' and '--txt-flag' and 'PKG_UNUSED_VAR_2'\n"
           "    out = main(['sub', '--fresh-flag=1', '--old', 'x', '--out', 'y', '--doc-only-flag'])\n"
           "    assert tools['new_tool'](x=2) == '' and tools['old_tool'] and tools['helper_not_a_tool']\n"
           "    assert 'exact words plugh' in out\n")}


def _fixture(tmp_path):
    _git(tmp_path, "init", "-q")
    _write(tmp_path, BASE)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    _write(tmp_path, FIX)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "fix")
    sha = lambda ref: subprocess.run(["git", "rev-parse", ref], cwd=tmp_path, capture_output=True,
                                     text=True, check=True).stdout.strip()
    return tmp_path / ".git", sha("HEAD^"), sha("HEAD")


WANT = ["MCP tool: new_tool(x: int=1) -> str",
        "CLI option: --fresh-flag", "CLI option: --out",
        "environment variable: PKG_NEW_VAR", "environment variable: PKG_SUB_VAR"]


def test_the_tests_named_strings_that_the_fix_adds_to_source_are_interface(tmp_path):
    mirror, base, fix = _fixture(tmp_path)
    assert interface.tests_call(mirror, base, fix) == WANT


def test_the_block_names_each_kind_and_states_no_expected_output(tmp_path):
    mirror, base, fix = _fixture(tmp_path)
    (t,) = history.refresh({"tasks": [{"base": base, "fix": fix, "context_files": ["pkg/cli.py"]}]}, mirror)["tasks"]
    row = {**t, "id": "fx-5", "issue": 5, "pr": 6, "date": "2026-10-22", "variant": "spec",
           "prompts": {"spec": "# Add a sub command"}, "fail_to_pass": ["tests/test_cli.py::test_flags_and_tools"],
           "pass_to_pass": []}
    prompt = history.convert(row).case["prompt"]
    assert "- MCP tool: `new_tool(x: int=1) -> str`" in prompt
    assert "- CLI option: `--fresh-flag`" in prompt and "- environment variable: `PKG_SUB_VAR`" in prompt
    for leak in ("plugh", "--old", "PKG_OLD_VAR", "PKG_NOT_READ", "old_tool", "helper_not_a_tool", "doc-only",
                 "fresh-flag=1", "unused", "UNUSED", "lower_name", "PKG_PRINTED", "txt-flag"):
        assert leak not in prompt, leak
