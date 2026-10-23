"""Every name a hidden test or graded id spells that the fix adds is in the prompt; a case that hides one is visible. #1141."""
import re

from evals import interface
from evals.importers import history
from tests.test_repo_interface_1103 import _git, _write

BASE = {"pkg/__init__.py": "", "pkg/store.py": "def _requeue_old(conn):\n    pass\n\n\nclass Store:\n    pass\n",
        "tests/__init__.py": ""}
FIX = {"pkg/store.py": ("WEIGHT = 2\n\n\ndef _requeue_old(conn):\n    pass\n\n\ndef _requeue_new(conn):\n    pass\n\n\n"
                        "def stated_fn():\n    pass\n\n\nclass Store:\n    field: int = 0\n\n    def update_x(self):\n"
                        "        def inner():\n            pass\n"),
       "tests/test_store.py": ("import re\nimport pytest\nfrom pkg import store\n\n\n"
                               "@pytest.mark.parametrize('fn', [n for n in dir(store) if re.match('_requeue_', n)])\n"
                               "def test_each(fn):\n    getattr(store, fn)(None)\n\n\n"
                               "def test_named():\n    assert store.WEIGHT and store.Store().update_x\n"
                               "    assert store.stated_fn and store.Store.field == 0 and 'inner'\n")}
IDS = ["tests/test_store.py::test_each[_requeue_new]", "tests/test_store.py::test_named"]


def _fixture(tmp_path):
    _git(tmp_path, "init", "-q")
    _write(tmp_path, BASE)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    _write(tmp_path, FIX)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "fix")
    import subprocess
    sha = lambda ref: subprocess.run(["git", "rev-parse", ref], cwd=tmp_path, capture_output=True,
                                     text=True, check=True).stdout.strip()
    return tmp_path / ".git", sha("HEAD^"), sha("HEAD")


def test_a_new_name_only_an_id_or_a_test_spells_is_unlisted_until_the_prompt_says_it(tmp_path):
    mirror, base, fix = _fixture(tmp_path)
    assert interface.unlisted(mirror, base, fix, "Fix it. Add `stated_fn`.", IDS) == [
        "WEIGHT", "_requeue_new", "update_x"]
    assert interface.unlisted(mirror, base, fix, "stated_fn WEIGHT _requeue_new and Store.update_x()", IDS) == []


def test_a_name_base_had_a_class_field_or_a_local_def_is_never_unlisted(tmp_path):
    mirror, base, fix = _fixture(tmp_path)
    got = interface.unlisted(mirror, base, fix, "", IDS)
    assert not {"_requeue_old", "Store", "field", "inner"} & set(got)


def test_every_committed_history_case_states_each_name_its_tests_spell():
    hidden = []
    for src in history.repos():
        for row in history.fetch(src=src):
            case = history.convert(row, src).case
            assert "unlisted" in row, f"{case['id']}: manifest has no unlisted; run --refresh"
            words = set(re.findall(r"[A-Za-z_]\w*", case["prompt"]))
            hidden += [f"{case['id']}: {n}" for n in row["unlisted"].get(row["variant"], []) if n not in words]
    assert not hidden, "names the hidden tests need that the prompt never gives (state them or retire the case): " \
        + ", ".join(hidden)
