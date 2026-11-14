"""Gauntlet OR (#1797): B done without A either does A itself or refuses; it never answers from the wrong place."""
import ast
import importlib.util
from pathlib import Path

import pytest
import yaml

from harness import chaos, downloads, engines, env, gguf, install_env, paths, remote_code, store

REPO = Path(__file__).resolve().parents[1]
HOME_KEYS = {"ENV_VAR", "LOCALHARNESS_HOME"}


# ---- OR-3: the backend is chosen with the home ---------------------------------------------------

def test_a_chaos_scratch_home_is_sqlite_where_the_store_names_postgres(monkeypatch, tmp_path):
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    with chaos.scratch_home(tmp_path, live=tmp_path / "live") as home:
        assert paths.home() == home
        assert store.backend() == store.SQLITE
    assert store.backend() == store.POSTGRES


def _key(node) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _passthrough(value) -> bool:
    """os.environ[...] or os.environ.get(...): the same home handed on, not a switch."""
    text = ast.unparse(value)
    return text.startswith(("os.environ[", "os.environ.get("))


def _home_writes(scope) -> list[int]:
    lines = []
    for node in ast.walk(scope):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            lines += [node.lineno for t in targets
                      if isinstance(t, ast.Subscript) and _key(t.slice) in HOME_KEYS]
        elif isinstance(node, ast.Dict):
            lines += [node.lineno for k, v in zip(node.keys, node.values)
                      if k is not None and _key(k) in HOME_KEYS and not _passthrough(v)]
    return lines


def _names_backend(scope) -> bool:
    return any(_key(n) in ("BACKEND_ENV", "LOCALHARNESS_STORE") for n in ast.walk(scope))


def test_every_code_path_that_switches_the_home_sets_the_backend_with_it():
    """A home switched without LOCALHARNESS_STORE keeps talking to the store the old home named (RULE #1441)."""
    bad = []
    for path in sorted([*(REPO / "harness").rglob("*.py"), *(REPO / "evals").rglob("*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        inside = {line for f in funcs for line in _home_writes(f)}
        for f in funcs:
            if _home_writes(f) and not _names_backend(f):
                bad.append(f"{path.relative_to(REPO).as_posix()}:{f.lineno} {f.name}")
        if set(_home_writes(tree)) - inside and not _names_backend(tree):
            bad.append(f"{path.relative_to(REPO).as_posix()}: module-level home mapping")
    assert not bad, f"these set the home but not {store.BACKEND_ENV}: {bad}"


def test_the_switch_scan_sees_a_home_set_without_its_backend():
    src = ("import os\nfrom harness import paths\nVARS = {paths.ENV_VAR: ''}\n"
           "def go(h):\n    os.environ[paths.ENV_VAR] = h\n")
    tree = ast.parse(src)
    assert _home_writes(tree) and not _names_backend(tree)
    assert not _home_writes(ast.parse("env = {paths.ENV_VAR: os.environ[paths.ENV_VAR]}\n"))


# ---- OR-4: the weights location is resolved on demand ---------------------------------------------

@pytest.fixture
def bare(monkeypatch):
    """A process started by hand or over ssh: nothing sourced env.sh."""
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv(env.ROOT_VAR, raising=False)
    monkeypatch.delenv("LLAMACPP_MODELS_DIR", raising=False)


def _record(hf):
    install_env.path(paths.machine_home()).write_text(f"PATH=/usr/bin\nHF_HOME={hf}\n", encoding="utf-8")


def test_a_bare_process_reads_the_weights_this_machines_install_recorded(bare, tmp_path):
    weights = tmp_path / "volume" / "hf"
    _record(weights)
    assert gguf.models_dir() == weights / "gguf"
    assert downloads.hf_home() == weights


def test_no_reader_falls_back_to_the_hub_cache_on_its_own():
    """conftest pins fetching.free_bytes, so its reader is held here: only env.weights_home spells the fallback."""
    bad = [f"{p.relative_to(REPO).as_posix()}:{n}" for p in sorted([*(REPO / "harness").rglob("*.py"),
                                                          *(REPO / "evals").rglob("*.py"),
                                                          *(REPO / "gateway").rglob("*.py")])
           if p != REPO / "harness" / "env.py"
           for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
           if '"huggingface"' in line and ".cache" in line]
    assert not bad, f"read the weights location through env.weights_home(): {bad}"


def test_a_bare_process_with_hf_root_reads_it(bare, tmp_path, monkeypatch):
    monkeypatch.setenv(env.ROOT_VAR, str(tmp_path / "root"))
    _record(tmp_path / "recorded")
    assert gguf.models_dir() == tmp_path / "root" / "gguf"


def test_hf_home_set_by_a_launcher_wins(bare, tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "unit"))
    monkeypatch.setenv(env.ROOT_VAR, str(tmp_path / "root"))
    _record(tmp_path / "recorded")
    assert downloads.hf_home() == tmp_path / "unit"


def test_with_nothing_recorded_it_is_huggingface_hubs_own_default(bare):
    assert downloads.hf_home() == Path.home() / ".cache" / "huggingface"


# ---- OR-7: the gateway callback reads the served config per request -------------------------------

def _entry(name, engine):
    return {"model_name": name, "engine": engine,
            "litellm_params": {"model": f"openai/{name}", "api_base": "http://far:8082/v1"}}


def test_schema_guard_sees_a_served_config_written_after_it_was_imported(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("schema_guard_1797", REPO / "gateway" / "schema_guard.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    base = tmp_path / "config.yaml"
    base.write_text(yaml.safe_dump({"model_list": [_entry("enforcer", "llama-server")]}), encoding="utf-8")
    monkeypatch.setattr(guard, "CONFIG", base)
    ask = {"model": "sohot-code", "response_format": {"type": "json_object"}}
    assert "sohot-code" in guard.refusal(ask)
    (tmp_path / "config.served.yaml").write_text(yaml.safe_dump({"model_list": [
        _entry("enforcer", "llama-server"), _entry("sohot-code", "llama-server")]}), encoding="utf-8")
    assert guard.refusal(ask) == ""


# ---- OR-8: values read from the environment when used, not when imported ---------------------------

def test_h3s_binary_follows_the_home_of_the_moment(monkeypatch, tmp_path):
    monkeypatch.delenv("H3_BIN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    eng = engines.resolve("h3")
    assert Path(eng.cwd).is_relative_to(tmp_path) and Path(eng.cwd).name == "h3.c"


def test_the_audio_servers_whisper_default_is_read_when_the_app_is_built(monkeypatch):
    pytest.importorskip("fastapi", reason="needs the `dev` group")
    from fastapi.testclient import TestClient
    from harness import audio_server
    monkeypatch.setenv("WHISPER_MODEL", "small.en")
    ids = [m["id"] for m in TestClient(audio_server.build_app()).get("/v1/models").json()["data"]]
    assert "small.en" in ids


# ---- OR-9: a cached file read is read again once the file changes ----------------------------------

def test_native_types_follows_a_rewritten_snapshot(monkeypatch, tmp_path):
    snap = tmp_path / "types.txt"
    snap.write_text("# transformers==1.0\nllama\n", encoding="utf-8")
    monkeypatch.setattr(remote_code, "SNAPSHOT", snap)
    assert remote_code.native_types() == ("transformers==1.0", frozenset({"llama"}))
    snap.write_text("# transformers==2.0\nllama\nnandi\n", encoding="utf-8")
    assert remote_code.native_types() == ("transformers==2.0", frozenset({"llama", "nandi"}))
