"""Every os.environ key the suite's heavy libraries set on import is in conftest.ENV_SETTLED. #1885."""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

from tests import conftest

#: What the suite imports torch with; `import torch` alone sets nothing, sklearn and mlx_lm (torch._dynamo) do.
IMPORTS = ("torch", "sklearn", "transformers.generation", "mlx_lm", "resemblyzer")

CHILD = '''
import importlib, json, os, sys
out = {}
for name in sys.argv[1:]:
    before = dict(os.environ)
    try:
        importlib.import_module(name)
    except ImportError:
        continue
    out[name] = sorted(k for k in set(before) | set(os.environ) if before.get(k) != os.environ.get(k))
print(json.dumps(out))
'''


def test_every_key_a_library_sets_on_import_is_settled():
    if importlib.util.find_spec("torch") is None:
        pytest.skip("torch is not installed (uv sync --group metrics)")
    env = {k: v for k, v in os.environ.items() if k not in conftest.ENV_SETTLED}
    done = subprocess.run([sys.executable, "-c", CHILD, *IMPORTS], env=env, capture_output=True, text=True,
                          timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    set_by = json.loads(done.stdout.strip().splitlines()[-1])
    assert "torch" in set_by
    unsettled = {name: [k for k in keys if k not in conftest.ENV_SETTLED] for name, keys in set_by.items()}
    assert not any(unsettled.values()), f"add to tests/conftest.py ENV_SETTLED: {unsettled}"
