"""Generated agent cases: deterministic, attributed, harder than the hand set, and enough holdout. #603."""
import collections
import functools
import re
from pathlib import Path

import pytest
import yaml

from evals import importers, sandbox
from evals.core import load_cases
from evals.importers import agent_synth as gen
from harness import holdout, power, privacy

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "evals" / "cases" / "agent"
OUT = LANE / "agent_synth"
#: The hand-written agent holdout before #603; growing the lane must leave each on its side.
HAND_HOLDOUT = 6


@functools.lru_cache(maxsize=None)
def rows():
    return gen.fetch()


def row_of(c):
    return rows()[int(c.id.rsplit("-", 1)[1])]


@pytest.fixture(scope="module")
def synth():
    return load_cases(OUT)


@pytest.fixture(scope="module")
def lane():
    return load_cases(LANE)


def _files(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


def test_the_generator_is_a_registered_agent_source():
    assert importers.Source("agent_synth", "agent") in importers.REGISTRY
    assert gen.LICENSE in importers.ALLOWED_LICENSES and len(gen.REVISION) == 40
    assert f"v{gen.VERSION} seed {gen.SEED}" in gen.SOURCE


def test_it_writes_the_same_bytes_twice_and_another_seed_draws_other_repos(tmp_path):
    importers.run("agent_synth", root=tmp_path / "a", rows=gen.fetch(count=16))
    importers.run("agent_synth", root=tmp_path / "b", rows=gen.fetch(count=16))
    one, two = _files(tmp_path / "a"), _files(tmp_path / "b")
    assert one and one == two
    assert len(load_cases(tmp_path / "a" / "agent" / "agent_synth")) == 16
    other = [gen.convert(r) for r in gen.fetch(seed=gen.SEED + 1, count=16)]
    assert [m.files for m in other] != [gen.convert(r).files for r in gen.fetch(count=16)]


def test_the_committed_cases_and_bundles_are_what_the_generator_writes(tmp_path):
    """Nothing in agent_synth/ is typed by hand: the committed tree is the generator's, byte for byte."""
    importers.run("agent_synth", root=tmp_path)
    assert _files(tmp_path / "agent" / "agent_synth") == _files(OUT)


def test_every_case_is_attributed_to_the_generator(synth):
    for c in synth:
        text = c.source.read_text(encoding="utf-8")
        assert text.startswith(f"# {gen.DATASET}, generated"), c.id
        att = yaml.safe_load(text)["attribution"]
        assert att["importer"] == gen.__name__ and att["revision"] == gen.REVISION, c.id
        assert att["version"] == gen.VERSION and att["seed"] == gen.SEED and att["license"] == "generated"
        assert att["kind"] in gen.KINDS and att["item"] == str(int(c.id.rsplit("-", 1)[1]))


def test_every_kind_is_drawn_in_turn_and_keeps_the_lane_families(synth):
    kinds = collections.Counter(re.match(r"agent-(\w+)-synth-", c.id).group(1) for c in synth)
    assert set(kinds) == {"fix", "edit", "refactor", "read"}
    by_kind = collections.Counter(row_of(c)["kind"] for c in synth)
    assert set(by_kind) == set(gen.KINDS)
    assert max(by_kind.values()) - min(by_kind.values()) <= 1
    for c in synth:
        assert set(c.params["tools"]) <= set(sandbox.TOOLS)
        if c.id.startswith("agent-read-"):
            assert c.assertions.get("answer") and "write_file" not in c.params["tools"], c.id
        else:
            assert c.assertions.get("hidden") and "run_tests" in c.params["tools"], c.id


def test_no_two_cases_in_the_lane_share_a_repo_and_prompt(lane):
    keys = [(c.prompt, c.params["repo_digest"], str(c.assertions)) for c in lane
            if "pad_tokens" not in c.params]
    assert len(keys) == len(set(keys))


def test_the_lane_reaches_both_power_targets(lane):
    """Holdout for the adopt gate at any incumbent rate, shared cases for a reverify to see a loss."""
    split = holdout.assign("agent", lane)
    effect = power.effect_for("agent")
    adopt_need = max(power.cases_needed([p / 20] * HAND_HOLDOUT, effect, rho=1.0) for p in range(1, 19))
    reverify_need = power.cases_needed([0.0] * 14, effect, rho=1.0, stochastic=False)
    assert len(split.holdout) >= adopt_need, (len(split.holdout), adopt_need)
    assert len(lane) >= reverify_need


def test_growing_the_lane_keeps_every_hand_case_on_its_side(lane):
    hand = [c for c in lane if "agent_synth" not in c.source.parts]
    alone, grown = holdout.assign("agent", hand), holdout.assign("agent", lane)
    assert len(alone.holdout) == HAND_HOLDOUT
    assert set(alone.holdout) <= set(grown.holdout)
    assert set(alone.dev) <= set(grown.dev)


def _box(c, files=()):
    box = sandbox.Sandbox.create(c.source.parent / c.params["repo"] / "repo")
    for rel, text in files:
        box.write_file(rel, text)
    return box


def _solution(c):
    sol = c.source.parent / c.params["repo"] / "solution"
    return [(f.relative_to(sol).as_posix(), f.read_text(encoding="utf-8")) for f in sol.rglob("*.py")]


@pytest.mark.parametrize("c", [c for c in load_cases(OUT) if c.assertions.get("hidden")],
                         ids=lambda c: c.id)
def test_the_visible_tests_pass_with_the_reference_and_fail_untouched_on_a_bug(c):
    """A bug case shows its failure; every reference leaves the visible suite green."""
    kind = row_of(c)["kind"]
    box = _box(c)
    try:
        before = box.run_tests()
        assert before.startswith("exit code 1" if kind in gen.BUGGY else "exit code 0"), before
    finally:
        box.cleanup()
    box = _box(c, _solution(c))
    try:
        assert box.run_tests().startswith("exit code 0")
    finally:
        box.cleanup()


@pytest.mark.parametrize("c", [c for c in load_cases(OUT) if c.assertions.get("answer")],
                         ids=lambda c: c.id)
def test_an_answer_case_takes_its_answer_and_refuses_every_decoy(c):
    item = row_of(c)
    right, decoys = gen.answers(item)
    assert decoys
    box = _box(c)
    try:
        assert sandbox.grade(box, None, c.assertions["answer"], f"It is {right}.")["passed"]
        for wrong in decoys:
            assert not sandbox.grade(box, None, c.assertions["answer"], f"It is {wrong}.")["passed"], wrong
    finally:
        box.cleanup()


def test_each_decoy_is_in_the_repo_so_a_skim_can_pick_it(synth):
    for c in [c for c in synth if c.assertions.get("answer")]:
        right, decoys = gen.answers(row_of(c))
        text = "\n".join(_files(c.source.parent / c.params["repo"] / "repo").keys()) + "\n" + "\n".join(
            b.decode("utf-8") for b in _files(c.source.parent / c.params["repo"] / "repo").values())
        assert right in text, c.id
        for wrong in decoys:
            assert wrong in text, (c.id, wrong)


def test_the_generated_text_passes_the_privacy_scanner(synth):
    for c in synth:
        bundle = c.source.parent / c.params["repo"]
        for rel, data in [(c.source.name, c.source.read_bytes())] + sorted(_files(bundle).items()):
            found = privacy.scan(data.decode("utf-8"), rel)
            assert not found, found


def test_the_negative_control_passes_the_reference_and_fails_the_untouched_repo(tmp_path):
    rows = gen.fetch(count=16)
    importers.run("agent_synth", root=tmp_path, rows=rows)
    cases = load_cases(tmp_path / "agent" / "agent_synth")
    got = importers.negative_control(cases, gen.RESPONDERS, gen.passes)
    assert got == {"reference": (16, 16), "untouched": (0, 16)}


def test_a_config_answer_is_what_the_settings_loader_returns(synth):
    import runpy
    for c in synth:
        item = row_of(c)
        if item["kind"] != "config":
            continue
        s = gen.scene(dict(item))
        load = runpy.run_path(str(c.source.parent / c.params["repo"] / "repo" / "app" / "settings.py"))["load"]
        assert load(s["check"]["env"])[s["check"]["key"]] == s["answer"], c.id


def test_a_located_function_is_defined_in_the_answer_file_and_nowhere_else(synth):
    import ast
    for c in synth:
        item = row_of(c)
        if item["kind"] != "locate":
            continue
        name, repo = gen.scene(dict(item))["check"]["name"], c.source.parent / c.params["repo"] / "repo"
        defined = [p.relative_to(repo).as_posix() for p in repo.rglob("*.py")
                   if any(isinstance(n, ast.FunctionDef) and n.name == name
                          for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))))]
        assert defined == [c.assertions["answer"][0]], c.id


def test_a_constant_answer_is_the_value_the_client_imports(synth):
    import subprocess
    import sys
    for c in synth:
        item = row_of(c)
        if item["kind"] != "constant":
            continue
        check = gen.scene(dict(item))["check"]
        code = f"import sys; sys.path.insert(0, '.'); import {check['module']} as m; print(m.{check['name']})"
        got = subprocess.run([sys.executable, "-I", "-c", code],
                             cwd=c.source.parent / c.params["repo"] / "repo", capture_output=True, text=True,
                             encoding="utf-8", timeout=60, check=True)
        assert got.stdout.strip() == c.assertions["answer"][0], c.id


def test_no_generated_package_shadows_the_standard_library():
    import sys
    assert not set(gen.PACKAGES) & set(sys.stdlib_module_names)


def test_a_planted_bug_that_no_input_catches_is_refused():
    fn = gen.FNS["clamp"]
    blind = gen.Fn(fn.name, fn.params, fn.doc, fn.body, bugs=(fn.body,), inputs=fn.inputs)
    with pytest.raises(ValueError, match="no input"):
        gen.caught(blind, 0)
