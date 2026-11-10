"""A cookbook, a skills pack or a component library is recorded and not filed; a real engine still is. #1532."""
from __future__ import annotations

import base64
import json

import pytest

from evals import redact
from harness import engine_trials as et
from tests.test_engine_trials_1475 import (EVIDENCE, FAKE_ENGINE, OPENAI_READING, UNTESTABLE, FakeGh, _asker,
                                           PLATFORM, _fake_uv, _readings, _tool, _waiting, conn, fake_digest)  # noqa: F401

#: The real GitHub reader, taken before the conftest guard replaces it; the test hands it a fake client.
REAL_GH_JSON = et._gh_json
COOKBOOK = "fakeorg/lfm-cookbook"
SKILLS = "fakeorg/mlx-skills"
COMPONENT = "fakeorg/tiny-autoencoders"

#: Shaped like the three repos the 11-04 sweep filed: the model read each as a runner with no interface.
SHAPES = {
    COOKBOOK: ({"kind": "runner", "why": "provides examples and applications for running LFM models",
                "interface": "", "serve": [], "model_types": []},
               et.Evidence(readme="**Examples**, **tutorials**, and **applications** to help you build with our "
                                  "open-weight LFMs on laptops, mobile, and edge devices.")),
    SKILLS: ({"kind": "runner", "why": "provides useful MLX skills as a runner", "interface": "", "serve": [],
              "model_types": []},
             et.Evidence(readme="# MLX Skills\n\nA repo of useful MLX skills.\n\n"
                                "uvx --from git+https://github.com/fakeorg/mlx-skills.git mlx-skills --codex",
                         scripts=["mlx-skills"])),
    COMPONENT: ({"kind": "runner", "why": "Provides a library to run specific model variants for diffusion latents",
                 "interface": "", "serve": [], "model_types": ["taesd", "taef1"]},
                et.Evidence(readme="Tiny AutoEncoders for diffusion latents.\n\n```python\nfrom tiny_ae import TAEF2\n"
                                   "img = TAEF2.from_pretrained().decode(latents)\n```",
                            pypi={"package": "tiny-autoencoders", "version": "0.4.0",
                                  "wheels": ["tiny_autoencoders-0.4.0-py3-none-any.whl"]},
                            scripts=["tiny-ae"])),
}


@pytest.fixture(autouse=True)
def sandbox_here(monkeypatch):
    monkeypatch.setattr(et, "can_sandbox", lambda: True)
    monkeypatch.setattr(et, "docker_here", lambda: True)


def _evidence(name):
    return SHAPES[name][1] if name in SHAPES else EVIDENCE[name]


def _sweep(conn, names, tmp_path, readings, gh):
    tools = [_tool(conn, n) for n in names]
    et.sweep(conn, tools, [_waiting(conn)], ask=_asker(**{n.replace("/", "_"): r for n, r in readings.items()}),
             evidence=_evidence, installer=lambda t, root: et.install(t, root, run=_fake_uv([]), digest=fake_digest, plat=PLATFORM),
             screener=lambda t, c: et.Screened(et.FAIL, 0, 1, "fake"), gh=gh, root=tmp_path / "trials",
             now=5000.0, known=redact.Known(accounts=("operator",), hosts=("trialbox",)))
    return tools


def test_the_three_shapes_read_as_runners_are_recorded_and_none_is_filed(conn, tmp_path):
    gh = FakeGh()
    tools = _sweep(conn, list(SHAPES), tmp_path, {n: r for n, (r, _) in SHAPES.items()}, gh)
    assert gh.created() == []
    states = {t.name: (t.state, t.issue) for t in et.trials(conn)}
    assert states == {n: (et.DROPPED, None) for n in SHAPES}
    out = "\n".join(et.lines(conn, tools, [], None))
    for n in SHAPES:
        assert f"dropped {n}: runner: not filed:" in out


def test_the_library_kind_drops_a_repo_whatever_its_packaging_shows(conn, tmp_path):
    gh = FakeGh()
    readings = {n: {**r, "kind": et.LIBRARY, "why": "a component library a runner imports"}
                for n, (r, _) in SHAPES.items()}
    _sweep(conn, list(SHAPES), tmp_path, readings, gh)
    assert gh.created() == [] and {(t.state, t.blocker) for t in et.trials(conn)} == {(et.DROPPED, "")}
    assert '"library"' in et.PROMPT and "cookbook" in et.PROMPT


def test_an_openai_server_with_a_command_its_readme_names_is_still_filed_beside_them(conn, tmp_path):
    gh = FakeGh()
    readings = {n: r for n, (r, _) in SHAPES.items()}
    readings[UNTESTABLE] = {**OPENAI_READING, "serve": ["c-serve", "-m", "{model}", "--port", "{port}"]}
    _sweep(conn, [*SHAPES, UNTESTABLE], tmp_path, readings, gh)
    (made,) = gh.created()
    assert f"{et.MARKER} {UNTESTABLE}" in made[made.index("--body") + 1]
    assert {t.name: t.state for t in et.trials(conn)}[UNTESTABLE] == et.BLOCKED


def test_an_openai_server_with_wheels_is_still_trialed(conn, tmp_path):
    gh = FakeGh()
    _sweep(conn, [FAKE_ENGINE, COOKBOOK], tmp_path, {FAKE_ENGINE: OPENAI_READING, COOKBOOK: SHAPES[COOKBOOK][0]}, gh)
    states = {t.name: t.state for t in et.trials(conn)}
    assert states == {FAKE_ENGINE: et.INSTALLED, COOKBOOK: et.DROPPED} and gh.created() == []


def test_an_unusable_reading_says_nothing_about_the_repo_and_is_not_filed(conn, tmp_path):
    gh = FakeGh()
    _sweep(conn, [COOKBOOK], tmp_path, {COOKBOOK: {"kind": "cookbook"}}, gh)
    (t,) = et.trials(conn)
    assert gh.created() == [] and t.state == et.DEFERRED and "unusable" in t.blocker


def test_a_server_reading_with_no_entry_point_anywhere_is_not_filed():
    reading = {**OPENAI_READING, "serve": ["ghost-serve", "--model", "{model}", "--port", "{port}"]}
    state, *_, why = et.plan(reading, et.Evidence(readme="a fast engine; build it with cmake"))
    assert state == et.DROPPED and "not filed" in why


@pytest.mark.parametrize("ev,shows", [
    (et.Evidence(scripts=["fast-serve"]), "fast-serve"),
    (et.Evidence(release={"tag": "b100", "wheels": [], "binaries": ["eng-b100-bin-macos-arm64.zip"]}), "b100"),
    (et.Evidence(readme="run `c-serve -m x --port 8080`"), "c-serve"),
    (et.Evidence(readme="answers POST /v1/chat/completions"), "OpenAI-compatible"),
])
def test_each_kind_of_entry_point_counts(ev, shows):
    reading = {**OPENAI_READING, "serve": ["c-serve", "-m", "{model}", "--port", "{port}"]}
    assert shows in et.entry_point(reading, ev)


def test_a_serve_name_inside_another_word_is_no_entry_point():
    reading = {**OPENAI_READING, "serve": ["serve", "{model}", "{port}"]}
    assert et.entry_point(reading, et.Evidence(readme="the fast-serve project; preserve it; serve.py")) == ""


@pytest.mark.parametrize("path,text,want", [
    ("pyproject.toml", '[project.scripts]\ntiny-ae = "tiny_ae.cli:main"\n[tool.poetry.scripts]\npo = "x:y"\n',
     ["po", "tiny-ae"]),
    ("pyproject.toml", '[project.entry-points.console_scripts]\nep = "x:y"\n', ["ep"]),
    ("pyproject.toml", "[project\nbroken", []),
    ("pyproject.toml", '[project]\nname = "only-a-library"\n', []),
    ("setup.cfg", "[options.entry_points]\nconsole_scripts =\n    cfg-serve = pkg.server:main\n", ["cfg-serve"]),
    ("setup.py", "setup(entry_points={'console_scripts': ['py-serve = pkg.server:main']})", ["py-serve"]),
    ("package.json", json.dumps({"name": "js-serve", "bin": "cli.js"}), ["js-serve"]),
    ("package.json", json.dumps({"bin": {"a": "a.js", "b": "b.js"}}), ["a", "b"]),
    ("Cargo.toml", '[package]\nname = "x"\n[[bin]]\nname = "rs-serve"\n', ["rs-serve"]),
    ("CMakeLists.txt", "add_executable(cpp-server server.cpp)\nadd_library(core core.cpp)\n", ["cpp-server"]),
])
def test_the_packaging_metadata_names_its_commands(path, text, want):
    assert et.entry_points(path, text) == want


class FakeClient:
    def __init__(self, files, release=None):
        self.files, self.release, self.asked = files, release, []

    def get(self, path):
        self.asked.append(path)
        if path.endswith("/contents"):
            return [{"name": n, "type": "file"} for n in self.files]
        if "/contents/" in path:
            text = self.files[path.split("/contents/", 1)[1]]
            return {"content": base64.b64encode(text.encode()).decode()}
        if path.endswith("/releases/latest") and self.release:
            return self.release
        raise RuntimeError("404")


def test_gather_reads_the_packaging_metadata_and_release_binaries(monkeypatch):
    monkeypatch.setattr(et, "_gh_json", REAL_GH_JSON)
    client = FakeClient({"README.md": "x", "pyproject.toml": '[project.scripts]\ntiny-ae = "a:b"\n'},
                        release={"tag_name": "v1", "assets": [{"name": "t-1-py3-none-any.whl"},
                                                              {"name": "t-v1-macos-arm64.tar.gz"},
                                                              {"name": "t-v1.sha256"}, {"name": "w.gguf"}]})
    ev = et.gather("fakeorg/t", client=client, pypi=lambda p: None)
    assert ev.scripts == ["tiny-ae"]
    assert ev.release == {"tag": "v1", "wheels": ["t-1-py3-none-any.whl"], "binaries": ["t-v1-macos-arm64.tar.gz"]}
    assert "repos/fakeorg/t/contents/README.md" not in client.asked
