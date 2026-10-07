"""Whether a repo needs trust_remote_code, from its card alone, before any download. #567.

    scripts/transformers-types.sh   rewrite the snapshot from the hf-task venv
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path

#: Model types the pinned transformers ships; its first line is `# <pin>`.
SNAPSHOT = Path(__file__).with_name("transformers_model_types.txt")


def code_evidence(config: dict, files) -> str:
    """The repo's own modelling code named by config.json's auto_map, or "" when it has none."""
    if not (config or {}).get("auto_map"):
        return ""
    names = sorted(b for b in (str(f).rsplit("/", 1)[-1] for f in files)
                   if b.endswith(".py") and b.startswith(("modeling_", "configuration_")))
    return ", ".join(names[:3]) or "auto_map"


def remote_code_gap(model_type: str, evidence: str, native, pin: str) -> str:
    """Why a runner that never passes trust_remote_code cannot load this repo, or ""."""
    if not evidence or not model_type or model_type in native:
        return ""
    return (f"ships its own modelling code ({evidence}) for model type {model_type!r}, "
            f"which {pin} does not ship")


@functools.lru_cache(maxsize=1)
def native_types() -> tuple[str, frozenset]:
    """(pin, model types) from the committed snapshot."""
    lines = SNAPSHOT.read_text(encoding="utf-8").splitlines()
    return lines[0].lstrip("# ").strip(), frozenset(x.strip() for x in lines[1:] if x.strip())


def gap(card) -> str:
    """remote_code_gap for a stored card row, against the snapshot."""
    card = card or {}
    pin, native = native_types()
    return remote_code_gap(str(card.get("model_type") or ""),
                           str(card.get("remote_code") or ""), native, pin)


def write_snapshot(path: Path = SNAPSHOT) -> int:
    """Rewrite the snapshot from the transformers this interpreter imports."""
    import transformers
    from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES
    names = sorted(CONFIG_MAPPING_NAMES)
    path.write_text(f"# transformers=={transformers.__version__}\n" + "\n".join(names) + "\n",
                    encoding="utf-8")
    print(f"{path.name}: {len(names)} model types from transformers {transformers.__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(write_snapshot())
