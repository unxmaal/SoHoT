# Requests with a slash in the model name fail with 500

Since upgrading to v1.2 the gateway answers every request whose model name
contains a slash (for example `mlx-community/Qwen3-8B-4bit`) with HTTP 500.
Requests to plain aliases still work. This worked in v1.1.

Steps: send any chat completion to the gateway with a slashed model name.
Expected: the answer. Actual: `500 Internal Server Error` and a traceback in the
gateway log ending in `KeyError: 'mlx-community'`.
