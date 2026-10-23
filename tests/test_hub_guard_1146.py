"""No test downloads from the Hugging Face Hub unless it is marked network or slow (#1146)."""
import huggingface_hub
import pytest


@pytest.mark.parametrize("name", ["hf_hub_download", "snapshot_download"])
def test_a_hub_download_is_refused(name):
    with pytest.raises(RuntimeError, match="real Hugging Face Hub"):
        getattr(huggingface_hub, name)(repo_id="org/x", filename="f.gguf")
