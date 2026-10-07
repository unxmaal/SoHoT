"""The suite never executes a real runtime binary on the machine it runs on. #536."""
import subprocess

import pytest

from conftest import runtime_binary


@pytest.mark.parametrize("argv,want", [
    (["llama-server", "--version"], "llama-server"),
    (["/opt/homebrew/bin/llama-server", "--version"], "llama-server"),
    ("llama-server --version", "llama-server"),
    (["uv", "run", "mlx_lm.server", "--port", "1"], "mlx_lm.server"),
    (["mflux-generate-z-image-turbo", "--prompt", "x"], "mflux-generate-z-image-turbo"),
    (["git", "status"], ""),
    (["python", "-c", "print('llama-server')"], ""),
])
def test_a_runtime_binary_is_named_by_its_argv(argv, want):
    assert runtime_binary(argv) == want


@pytest.mark.real_runtime
def test_a_runtime_binary_answers_as_absent_and_is_recorded(_no_real_runtime):
    # Marked so the recorded call is this test's own and does not fail it.
    with pytest.raises(FileNotFoundError):
        subprocess.run(["llama-server", "--version"], capture_output=True)
    assert _no_real_runtime == [["llama-server", "--version"]]
    assert subprocess.run(["true"]).returncode == 0
