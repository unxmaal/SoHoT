# shellcheck shell=bash
# shellcheck disable=SC2034  # every pin is consumed by a script that sources this
# Pinned service dependencies. Sourced by the launchers; never run directly.
#
# `uv run --with litellm[proxy]` resolves the LATEST release on every launch, so
# a restart silently changes 107 packages. That is the opposite of what this
# machine is for: a measurement from last week and one from today would have
# been produced by different software, and nothing would say so. The gateway
# restart in this session downloaded 22.5 MiB and reinstalled 107 packages
# before it could serve.
#
# These are the versions the suite was last verified against.
#
# TO BUMP ONE: change it here, restart the service, and run ./scripts/smoke.sh.
# It exits non-zero if the architecture's assumptions broke, which is exactly
# what an upgrade is most likely to do -- the /v1/messages routing regression
# this repo exists to remember came from a LiteLLM release.

LITELLM_PIN="litellm[proxy]==1.100.0"

MLX_AUDIO_PIN="mlx-audio==0.5.3"
MISAKI_PIN="misaki[en]==0.9.4"
WEBRTCVAD_PIN="webrtcvad==2.0.10"
FASTAPI_PIN="fastapi==0.141.1"
UVICORN_PIN="uvicorn==0.52.4"
MULTIPART_PIN="python-multipart==0.0.32"
# RULE #143, and a range on purpose. webrtcvad still imports pkg_resources, uv
# does not install setuptools into venvs on Python 3.12+, and setuptools >= 81
# removed pkg_resources outright, so unpinned resolves to 84.x and mlx_audio
# dies on import. Any 70-80 works; nothing above 81 does.
SETUPTOOLS_PIN="setuptools>=70,<81"

# llama.cpp is a winget binary rather than a uv --with, so this RECORDS the
# build the text lane was last verified against instead of pinning it:
# scripts/serve-llamacpp.sh cannot install its own server. Bump it with
# `winget upgrade --id ggml.llamacpp`, then run ./scripts/smoke.sh.
LLAMACPP_BUILD="b10869"

# The audio lanes on a machine with an NVIDIA card, served by
# harness/audio_server.py. The two nvidia wheels carry the CUDA runtime that
# CTranslate2 needs, which is why no system CUDA install appears anywhere here.
FASTER_WHISPER_PIN="faster-whisper==1.2.1"
KOKORO_ONNX_PIN="kokoro-onnx==0.6.1"
SOUNDFILE_PIN="soundfile==0.14.0"
NVIDIA_CUBLAS_PIN="nvidia-cublas-cu12==12.9.2.10"
NVIDIA_CUDNN_PIN="nvidia-cudnn-cu12==9.25.1.1"

# The image lane on a machine with an NVIDIA card, built by
# scripts/image-diffusers.sh into a venv of its own. torch+cu124 is only on
# PyTorch's index and the rest are only on PyPI, which is why the script
# installs them in two steps.
TORCH_CUDA_INDEX="https://download.pytorch.org/whl/cu124"
TORCH_CUDA_PIN="torch==2.6.0+cu124"
# The same torch on Apple Silicon, where Metal support is in the ordinary PyPI
# wheel and the +cu124 build does not exist at all. Same MINOR version as the
# CUDA pin so the two machines run the same diffusers against the same API.
TORCH_MPS_PIN="torch==2.6.0"
# torchvision 0.21 is the one built against torch 2.6; transformers image processors need it. #601.
TORCHVISION_CUDA_PIN="torchvision==0.21.0+cu124"
TORCHVISION_MPS_PIN="torchvision==0.21.0"
DIFFUSERS_PIN="diffusers==0.40.0"
TRANSFORMERS_PIN="transformers==5.17.0"
ACCELERATE_PIN="accelerate==1.15.0"
SAFETENSORS_PIN="safetensors==0.8.0"
PILLOW_PIN="pillow==12.3.0"
# The hf-task engines: OCR tokenizers ship slow sentencepiece models (trocr). #562.
SENTENCEPIECE_PIN="sentencepiece==0.2.2"
# The retrieval lane's rerank: and embed: engines (CrossEncoder, SentenceTransformer). #563.
SENTENCE_TRANSFORMERS_PIN="sentence-transformers==6.1.0"

# The decide lane's nimble engine (#423), built by scripts/nimble-venv.sh. The
# checkout is pinned by commit; its requirements/mlx.txt and training.txt pins
# are repeated here so a rebuild cannot drift.
NIMBLE_REPO_URL="https://github.com/bespokelabsai/nimble.git"
NIMBLE_REV="dcfdbd9a64f0d869f658d7a72f1beaee32737773"
NIMBLE_MLX_PIN="mlx==0.32.2"
NIMBLE_MLX_LM_PIN="mlx-lm==0.31.3"
NIMBLE_TORCH_PIN="torch==2.8.0"
PEFT_PIN="peft==0.21.0"

# The decide lane's decider engine (#467), built by scripts/decider-venv.sh.
# PyPI 0.1.0 lacks the mlx extra, so it installs from a clone at this commit.
DECIDER_REPO_URL="https://github.com/strands-labs/strands-decider.git"
DECIDER_REV="3e94e9d84c620ed5a95f1a3310c3decb971e261c"
DECIDER_MLX_LM_PIN="mlx-lm==0.32.0"
