"""Claude Code statusLine: print a short line and keep the plan's rate-limit readings. Stdlib only. #826."""
import json
import os
import sys
import time
from pathlib import Path

WINDOWS = ("five_hour", "seven_day")
#: Seconds between two identical readings before the second is written anyway.
MIN_GAP_S = 300.0


def _window(rl: dict, name: str) -> dict:
    got = rl.get(name)
    return got if isinstance(got, dict) else {}


def sample(data: dict, now: float) -> dict | None:
    rl = data.get("rate_limits")
    if not isinstance(rl, dict):
        return None
    rec = {"at": now}
    for name in WINDOWS:
        w = _window(rl, name)
        pct = w.get("used_percentage")
        rec[name] = pct if isinstance(pct, (int, float)) else None
        rec[f"{name}_resets_at"] = w.get("resets_at")
    if all(rec[name] is None for name in WINDOWS):
        return None
    return rec


def store_path(environ) -> Path:
    local = environ.get("LOCALHARNESS_HOME")
    if local:
        return Path(local) / "ledger" / "ratelimits.jsonl"
    home = environ.get("HOME") or Path.home()
    return Path(home) / "localharness" / "ledger" / "ratelimits.jsonl"


def _last(path: Path) -> dict | None:
    if not path.exists():
        return None
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(max(0, size - 4096))
        tail = fh.read().decode("utf-8", "replace")
    lines = [ln for ln in tail.splitlines() if ln.strip()]
    try:
        got = json.loads(lines[-1]) if lines else None
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def _repeat(last: dict | None, rec: dict, gap_s: float) -> bool:
    if last is None:
        return False
    keys = [k for name in WINDOWS for k in (name, f"{name}_resets_at")]
    at = last.get("at")
    return all(last.get(k) == rec.get(k) for k in keys) and isinstance(at, (int, float)) and rec["at"] - at < gap_s


def append(path: Path, rec: dict, min_gap_s: float = MIN_GAP_S) -> bool:
    if _repeat(_last(path), rec, min_gap_s):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return True


def line(data: dict, rec: dict | None) -> str:
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    parts = [str(model.get("display_name") or model.get("id") or "claude")]
    for name, label in zip(WINDOWS, ("5h", "7d")):
        if rec and rec.get(name) is not None:
            parts.append(f"{label} {round(rec[name])}%")
    return " | ".join(parts)


def main(stdin=sys.stdin, stdout=sys.stdout, environ=os.environ, now=None) -> int:
    now = time.time() if now is None else now
    try:
        data = json.loads(stdin.read() or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    rec = sample(data, now)
    if rec:
        try:
            append(store_path(environ), rec)
        except OSError:
            rec = None
    stdout.write(line(data, rec) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
