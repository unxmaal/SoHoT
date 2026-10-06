"""The gateway demands a key and the engines behind it listen on loopback. #482."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from harness import gateway
from tests.shells import BASH

REPO = Path(__file__).resolve().parents[1]
CONFIGS = [REPO / "gateway" / "config.yaml", REPO / "gateway" / "config.cuda.yaml"]


@pytest.mark.parametrize("path", CONFIGS, ids=["mac", "cuda"])
def test_both_configs_take_the_master_key_from_the_environment(path):
    """Never the key itself: the config is committed."""
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert body["general_settings"]["master_key"] == "os.environ/LITELLM_MASTER_KEY"


def test_the_served_config_keeps_the_master_key():
    got = gateway.served(CONFIGS[0], defaults={})
    assert got["general_settings"]["master_key"] == "os.environ/LITELLM_MASTER_KEY"


FAKE_UV = """#!{python}
import os, sys
args = sys.argv[1:]
if "harness.gateway_key" in args:
    print(os.environ.get("FAKE_KEY", ""))
elif "harness.gateway" in args:
    print(args[-1])
elif "litellm" in args:
    print("LITELLM_MASTER_KEY=" + os.environ.get("LITELLM_MASTER_KEY", ""))
    print("ARGS=" + " ".join(args))
"""


def _serve(tmp_path, fake_key: str):
    if not BASH or sys.platform == "win32":
        pytest.skip("needs a POSIX bash")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV.format(python=sys.executable), encoding="utf-8")
    uv.chmod(0o755)
    hf = tmp_path / "hf"
    hf.mkdir()
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "FAKE_KEY": fake_key, "HF_ROOT": str(hf), "HF_HOME": str(hf),
           "HF_MIN_FREE_GB": "0", "LOCALHARNESS_HOME": str(tmp_path / "home"),
           "PYTHONUTF8": "1"}
    env.pop("LITELLM_MASTER_KEY", None)
    return subprocess.run([BASH, "scripts/serve-gateway.sh"], cwd=REPO, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=60)


def test_the_launcher_hands_litellm_the_machines_key(tmp_path):
    r = _serve(tmp_path, "sk-machine")
    assert "LITELLM_MASTER_KEY=sk-machine" in r.stdout, r.stdout + r.stderr


def test_the_launcher_refuses_to_serve_without_a_key(tmp_path):
    """LiteLLM with no master key serves everyone: fail closed instead."""
    r = _serve(tmp_path, "")
    assert r.returncode != 0
    assert "LITELLM_MASTER_KEY" not in r.stdout
    assert "soh gateway key" in r.stderr


@pytest.mark.parametrize("script,var", [("scripts/serve-llamacpp.sh", "LLAMACPP_HOST"),
                                        ("scripts/serve-mlx.sh", "MLX_HOST")])
def test_the_engines_behind_the_gateway_listen_on_loopback(script, var):
    """They take no key; the gateway in front of them does."""
    text = (REPO / script).read_text(encoding="utf-8")
    assert re.search(rf'\$\{{{var}:-127\.0\.0\.1\}}', text)


def test_status_probes_the_gateway_where_no_key_is_needed():
    """/v1/models answers 401 to a keyless probe, which would read as down."""
    text = (REPO / "scripts" / "services.sh").read_text(encoding="utf-8")
    body = text[text.index("probe_for()"):]
    probe = re.search(r"gateway\)\s+printf '([^']*)'", body)
    assert probe and probe.group(1) == "/health/liveliness"
