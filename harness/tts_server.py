"""mlx_audio.server that hands a removed model's memory back to the machine. #1671."""
from __future__ import annotations

import gc

#: What this wraps; scripts/serve-tts.sh runs it with mlx-audio's own pins, so only the stdlib is imported here.
WRAPS = "mlx_audio.server"


def free_on_remove(provider_cls, clear) -> None:
    """After DELETE /v1/models drops a model, collect it and empty MLX's buffer cache, which otherwise keeps every byte."""
    original = provider_cls.remove_model

    async def remove_model(self, model_name: str) -> bool:
        removed = await original(self, model_name)
        if removed:
            gc.collect()
            clear()
        return removed

    provider_cls.remove_model = remove_model


def main() -> None:
    try:
        import mlx.core as mx
        from mlx_audio import server
    except ImportError as exc:  # pragma: no cover - mlx-audio is darwin-only
        raise SystemExit(f"{WRAPS} is not installed: {exc}") from exc
    free_on_remove(server.ModelProvider, mx.clear_cache)
    server.main()


if __name__ == "__main__":
    main()
