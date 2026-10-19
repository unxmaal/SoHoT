"""#1045: misaki's English G2P loads en_core_web_sm, and downloads it from GitHub per request when the audio server's env lacks it."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from harness import runner_gaps
from tests import shells

REPO = Path(__file__).resolve().parents[1]
VERSIONS = (REPO / "scripts" / "versions.sh").read_text(encoding="utf-8")

FAKE_UV = """#!{python}
import json, os, sys
json.dump(sys.argv[1:], open(os.environ["UV_ARGV"], "w", encoding="utf-8"))
"""

#: misaki 0.9.4 en.G2P.__init__: download when spaCy does not see the package, then load it.
STUB_MISAKI = """import os, spacy.util
class G2P:
    def __init__(self):
        if not spacy.util.is_package("en_core_web_sm"):
            open(os.environ["DOWNLOADED"], "w").close()
"""


def _pin(name: str) -> str:
    return re.search(rf'^{name}="([^"]*)"', VERSIONS, re.M).group(1)


def test_the_audio_server_env_holds_the_spacy_model_misaki_loads(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert {"spacy", "en-core-web-sm"} <= runner_gaps.installs(runner_gaps.AUDIO_ENV)


def test_the_spacy_model_is_built_for_the_pinned_spacy_minor():
    model = re.search(r"en_core_web_sm-(\d+\.\d+)\.\d+-py3-none-any\.whl$", _pin("EN_CORE_WEB_SM_PIN"))
    spacy = re.fullmatch(r"spacy==(\d+\.\d+)\.\d+", _pin("SPACY_PIN"))
    assert model and spacy and model.group(1) == spacy.group(1)


def _argv(tmp_path, *args) -> list[str]:
    if sys.platform == "win32" or not shells.BASH:
        pytest.skip("runs a bash script with a fake uv")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV.format(python=sys.executable), encoding="utf-8")
    uv.chmod(0o755)
    hf = tmp_path / "hf"
    hf.mkdir(exist_ok=True)
    out = tmp_path / "argv.json"
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "UV_ARGV": str(out),
           "HF_ROOT": str(hf), "HF_HOME": str(hf), "HF_MIN_FREE_GB": "0",
           "LOCALHARNESS_HOME": str(tmp_path / "home"), "PYTHONUTF8": "1"}
    subprocess.run([shells.BASH, "scripts/serve-tts.sh", *args], cwd=REPO, env=env, check=True,
                   capture_output=True, text=True, encoding="utf-8", timeout=60)
    return json.loads(out.read_text(encoding="utf-8"))


def test_the_check_runs_in_the_servers_own_env(tmp_path):
    serve, check = _argv(tmp_path), _argv(tmp_path, "--check")
    head = serve[:serve.index("python")]
    assert check[:check.index("python")] == head
    assert _pin("EN_CORE_WEB_SM_PIN") in head
    assert serve[serve.index("python") + 1:][:2] == ["-m", "mlx_audio.server"]
    assert check[check.index("python") + 1] == "-c"


@pytest.mark.parametrize("installed, rc", [(False, 1), (True, 0)])
def test_the_check_fails_without_the_model_and_never_downloads_it(tmp_path, installed, rc):
    argv = _argv(tmp_path, "--check")
    code = argv[argv.index("-c") + 1]
    stubs = tmp_path / "stubs"
    (stubs / "spacy").mkdir(parents=True)
    (stubs / "misaki").mkdir()
    (stubs / "spacy" / "__init__.py").write_text("", encoding="utf-8")
    (stubs / "spacy" / "util.py").write_text(f"def is_package(name):\n    return {installed}\n", encoding="utf-8")
    (stubs / "misaki" / "__init__.py").write_text("", encoding="utf-8")
    (stubs / "misaki" / "en.py").write_text(STUB_MISAKI, encoding="utf-8")
    downloaded = tmp_path / "downloaded"
    r = subprocess.run([sys.executable, "-c", code], cwd=stubs, capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PYTHONPATH": str(stubs), "DOWNLOADED": str(downloaded)})
    assert r.returncode == rc, r.stderr
    assert not downloaded.exists()
    assert installed or "en_core_web_sm" in r.stderr


def test_smoke_runs_the_check():
    assert "scripts/serve-tts.sh --check" in (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
