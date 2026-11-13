"""One real completion through the gateway for each upstream engine this machine serves (#1518)."""
from __future__ import annotations

import sys

#: How long one engine's completion may take, a cold model load included.
ASK_TIMEOUT_S = 300.0


def picks(data: dict) -> dict[str, str]:
    """engine -> the first model the gateway routes to it on this machine, lane aliases and node routes left out."""
    from harness import gateway, nodes, serving
    out: dict[str, str] = {}
    for entry in data.get("model_list") or []:
        name = str(entry.get("model_name", ""))
        if (not name or gateway.hosted(entry) or entry.get(nodes.NODE_KEY) or entry.get(nodes.FALLBACK_KEY)
                or name.startswith(gateway.LANE_ALIAS.format(""))):
            continue
        base = serving.api_base(entry)
        if not base or not serving.loopback(base):
            continue
        try:
            engine = nodes._local_engine(entry, data)
        except ValueError:
            continue
        if engine and engine not in out:
            out[engine] = name
    return out


def smoke(gateway_url: str, key: str, data: dict, timeout: float, ask=None) -> list[tuple[bool, str]]:
    from harness import cuts, nodes
    ask = ask or nodes._ask
    out = []
    for engine, model in picks(data).items():
        try:
            with cuts.timeout("harness/engine_smoke.py:ASK_TIMEOUT_S", f"smoke completion from {engine}"):
                r = ask(gateway_url, key, model, timeout)
        except Exception as exc:  # noqa: BLE001 - any failure to answer fails the engine
            out.append((False, f"engine {engine}: {model} got no answer ({exc})"))
            continue
        body = getattr(r, "text", "") or ""
        if r.status_code >= 400 or '"content"' not in body:
            out.append((False, f"engine {engine}: {model} answered HTTP {r.status_code}: {body[:200]}"))
        else:
            out.append((True, f"engine {engine} completes ({model})"))
    return out


def load() -> dict:
    """The config the gateway serves: its generated copy when there is one, else the base."""
    from harness import gateway
    served = gateway.serving_path()
    return gateway.load(served if served.is_file() else None)


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m harness.engine_smoke")
    p.add_argument("--gateway", required=True)
    args = p.parse_args(argv)
    from harness import gateway_key
    rows = smoke(args.gateway, gateway_key.key(), load(), ASK_TIMEOUT_S)
    for ok, line in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {line}")
    if not rows:
        print("SKIP  the gateway routes to no engine on this machine")
    return 0 if all(ok for ok, _ in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
