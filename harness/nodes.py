"""Serving nodes: another machine's server, tried first for the models it holds, the gateway's own copy after. #684.

The list is per machine and never committed: $LOCALHARNESS_HOME/nodes.yaml. gateway/nodes.example.yaml shows it.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

FILE = "nodes.yaml"
#: Overrides where the node list is read from.
ENV_VAR = "SOHOT_NODES"
#: The gateway's own copy of a node-routed entry is served under its name plus this.
LOCAL_SUFFIX = "@local"
#: Served config entry keys: the node an entry goes to, its identity, and the name a local copy stands in for.
NODE_KEY = "node"
MACHINE_KEY = "node_machine"
CONNECT_KEY = "connect_timeout"
IPV4_KEY = "ipv4"
FALLBACK_KEY = "fallback_for"
#: The refusal for a down node's model with no local twin; smoke matches it. #823.
NO_LOCAL_COPY = "this machine has no copy of"

CONNECT_TIMEOUT_S = 3.0
#: Covers a cold reload after --sleep-idle-seconds plus a long reply.
TIMEOUT_S = 120.0
#: How long LiteLLM skips a node after a timeout or a refused connection.
COOLDOWN_S = 30.0
#: Every failure class that means "this node, not the request": cool it down at once.
COOL_ON = ("TimeoutErrorAllowedFails", "InternalServerErrorAllowedFails",
           "ServiceUnavailableErrorAllowedFails", "BadGatewayErrorAllowedFails",
           "AuthenticationErrorAllowedFails", "NotFoundErrorAllowedFails")
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_KEY = re.compile(r"^(env:[A-Za-z_][A-Za-z0-9_]*|keychain:[^/\s]+/[^/\s]+)$")


@dataclass(frozen=True)
class Node:
    name: str
    api_base: str
    engine: str
    models: tuple[str, ...]
    key: str = ""
    machine: str = ""
    connect_timeout: float = CONNECT_TIMEOUT_S
    timeout: float = TIMEOUT_S
    cooldown: float = COOLDOWN_S
    #: An mDNS name can resolve to a link-local IPv6 address first that never connects.
    ipv4: bool = True
    #: (gateway id, the id the node advertises) where they differ, e.g. a router's models-dir stem.
    renamed: tuple[tuple[str, str], ...] = ()

    def node_id(self, model: str) -> str:
        """The id this node is sent for a gateway model id."""
        return dict((k.lower(), v) for k, v in self.renamed).get(model.lower(), model)

    @property
    def key_var(self) -> str:
        """The environment variable LiteLLM reads this node's key from."""
        if self.key.startswith("env:"):
            return self.key[4:]
        return f"SOHOT_NODE_{re.sub(r'[^A-Z0-9]', '_', self.name.upper())}_KEY" if self.key else ""

    @property
    def fingerprint(self) -> str:
        """The node's hw_model/OS family/arch/host, "" when `machine:` does not name all four. #781."""
        from harness import machine
        got = machine.parse_fingerprint(self.machine)
        # The OS family, never a build string that changes with every update. #781.
        return machine.fingerprint(got["hw_model"], got["os"], got["arch"], got["host"]) if got else ""

    @property
    def identity(self) -> str:
        """What x-sohot-machine and a receipt name: the node's fingerprint, else node:<name>."""
        return self.fingerprint or f"node:{self.name}"


def unidentified(node: Node) -> str:
    """Why a node's runs would be filed under no machine, or "" when its fingerprint is whole. #781."""
    if node.fingerprint:
        return ""
    have = f"`machine: {node.machine}` is not" if node.machine else "it has no `machine:`, which must be"
    return (f"node {node.name}: {have} hw_model/os/arch/host in {path()}, so its runs are stored with "
            f"no machine; run `python -m harness.nodes fingerprint` on the node and paste the line")


def path(environ=None) -> Path:
    environ = os.environ if environ is None else environ
    from harness import paths
    raw = (environ.get(ENV_VAR) or "").strip()
    return Path(raw).expanduser() if raw else paths.home() / FILE


def _number(raw: dict, key: str, default: float, where: str) -> float:
    try:
        got = float(raw.get(key, default))
    except (TypeError, ValueError):
        raise ValueError(f"{where}: {key} must be a number of seconds") from None
    if got <= 0:
        raise ValueError(f"{where}: {key} must be positive")
    return got


def parse(data: dict, where: str = FILE) -> list[Node]:
    """The nodes a parsed nodes.yaml names; ValueError naming the field for anything malformed."""
    from urllib.parse import urlsplit

    from harness import serving
    out, seen = [], set()
    for i, raw in enumerate((data or {}).get("nodes") or []):
        at = f"{where}: nodes[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{at} is not a mapping")
        name = str(raw.get("name") or "").strip()
        if not _NAME.match(name) or name in seen:
            raise ValueError(f"{at}: name {name!r} must be unique, lower case, letters digits and -")
        seen.add(name)
        base = str(raw.get("api_base") or "").strip().rstrip("/")
        split = urlsplit(base)
        try:
            port = split.port
        except ValueError:
            port = None
        if split.scheme not in ("http", "https") or not split.hostname or not port:
            raise ValueError(f"{at}: api_base {base!r} must be http(s)://host:port/v1")
        engine = str(raw.get("engine") or "").strip()
        if engine not in serving.engines():
            raise ValueError(f"{at}: engine {engine!r} is not one of "
                             f"{', '.join(dict.fromkeys(serving.engines()))}")
        models, renamed = [], []
        for m in raw.get("models") or []:
            if isinstance(m, dict):
                gid, nid = str(m.get("id") or "").strip(), str(m.get("as") or "").strip()
                if gid and nid:
                    models.append(gid)
                    if nid != gid:
                        renamed.append((gid, nid))
                    continue
            elif isinstance(m, str) and m.strip():
                models.append(m.strip())
                continue
            models = []
            break
        if not models:
            raise ValueError(f"{at}: models must be a list of model ids, or of {{id, as}} where the "
                             f"node advertises a model under another id")
        key = str(raw.get("key") or "").strip()
        if key and not _KEY.match(key):
            raise ValueError(f"{at}: key must be env:<VAR> or keychain:<service>/<account>, "
                             f"never the key itself")
        out.append(Node(name, base if base.endswith("/v1") else base + "/v1", engine,
                        tuple(models), key,
                        str(raw.get("machine") or "").strip(),
                        _number(raw, "connect_timeout", CONNECT_TIMEOUT_S, at),
                        _number(raw, "timeout", TIMEOUT_S, at),
                        _number(raw, "cooldown", COOLDOWN_S, at),
                        bool(raw.get("ipv4", True)), tuple(renamed)))
    return out


def load(file=None) -> list[Node]:
    """This machine's nodes; [] when it has no nodes.yaml."""
    import yaml
    where = Path(file) if file else path()
    try:
        text = where.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return parse(yaml.safe_load(text) or {}, str(where))


def keychain(service: str, account: str) -> str:
    """A generic password from the login Keychain, "" when there is none."""
    if sys.platform != "darwin":
        return ""
    try:
        out = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account,
                              "-w"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def secret(node: Node, environ=None, lookup=keychain) -> str:
    """The node's key: its environment variable when set, else the Keychain item it names."""
    environ = os.environ if environ is None else environ
    if not node.key:
        return ""
    got = (environ.get(node.key_var) or "").strip()
    if got or not node.key.startswith("keychain:"):
        return got
    service, _, account = node.key[len("keychain:"):].partition("/")
    return lookup(service, account)


def exports(nodes: list[Node], environ=None, lookup=keychain) -> list[str]:
    """Shell lines exporting each Keychain-held key for LiteLLM's os.environ/ reference."""
    out = []
    for node in nodes:
        if node.key.startswith("keychain:"):
            got = secret(node, environ, lookup)
            if got:
                out.append(f"export {node.key_var}={shlex.quote(got)}")
            else:
                print(f"warning: no Keychain item for node {node.name} ({node.key}); "
                      f"its requests will be refused and fall back", file=sys.stderr)
    return out


def _local_engine(entry: dict, data: dict) -> str | None:
    from harness import serving
    declared = str(entry.get(serving.ENGINE_KEY) or "").strip()
    return declared or serving.engine_at(serving.api_base(entry), data=data)


def _to_node(entry: dict, node: Node, model: str) -> dict:
    params = {k: v for k, v in (entry.get("litellm_params") or {}).items()
              if k != "max_parallel_requests"}
    params.update(model=f"openai/{node.node_id(model)}", api_base=node.api_base, timeout=node.timeout, max_retries=0,
                  api_key=f"os.environ/{node.key_var}" if node.key_var else "not-needed")
    info = dict(entry.get("model_info") or {})
    info.update(allowed_fails_policy={k: 0 for k in COOL_ON}, cooldown_time=node.cooldown)
    keep = {k: v for k, v in entry.items() if k not in ("hot_swap", "litellm_params", "model_info")}
    return {**keep, "engine": node.engine, NODE_KEY: node.name, MACHINE_KEY: node.identity,
            CONNECT_KEY: node.connect_timeout, IPV4_KEY: node.ipv4, "litellm_params": params,
            "model_info": info}


def route(data: dict, nodes: list[Node]) -> dict:
    """A gateway config whose entries for a node's models go to the node, each with a fallback
    to this machine's copy; an entry moves only when the node runs the engine its own server does."""
    from harness import gateway, models, serving
    if not nodes:
        return data
    holder = {}
    for node in nodes:
        for model in node.models:
            holder.setdefault(model.lower(), node)
    entries, twins, fallbacks, held = [], [], [], set()
    for entry in data.get("model_list") or []:
        params = entry.get("litellm_params") or {}
        model = gateway.strip_provider(str(params.get("model", "")))
        node = holder.get(model.lower())
        base = serving.api_base(entry)
        try:
            same = bool(base) and serving.loopback(base) and node is not None \
                and _local_engine(entry, data) == node.engine
        except ValueError:
            same = False
        if not same:
            entries.append(entry)
            continue
        name = str(entry["model_name"])
        held.add(model.lower())
        entries.append(_to_node(entry, node, model))
        twin = {k: v for k, v in entry.items() if k != models.DEPRECATED_KEY}
        twins.append({**twin, "model_name": name + LOCAL_SUFFIX, FALLBACK_KEY: name})
        fallbacks.append({name: [name + LOCAL_SUFFIX]})
    for node in nodes:
        for model in node.models:
            if model.lower() not in held and not any(
                    str(e.get("model_name", "")).lower() == model.lower() for e in entries):
                held.add(model.lower())
                entries.append(_to_node({"model_name": model, "litellm_params": {}}, node, model))
    settings = dict(data.get("router_settings") or {})
    if fallbacks:
        settings["fallbacks"] = list(settings.get("fallbacks") or []) + fallbacks
    out = {**data, "model_list": entries + twins}
    if settings:
        out["router_settings"] = settings
    if any(n.ipv4 for n in nodes):
        # LiteLLM has one switch for every upstream; loopback and the hosted API answer on IPv4 too.
        out["litellm_settings"] = {**(data.get("litellm_settings") or {}), "force_ipv4": True}
    return out


def by_base(base: str, nodes: list[Node]) -> Node | None:
    from harness import serving
    want = serving.bare(base)
    return next((n for n in nodes if serving.bare(n.api_base) == want), None) if want else None


def _probe(node: Node, get) -> tuple[bool, set]:
    """(whether the node answers, the model ids it advertises)."""
    try:
        status, ids = get(f"{node.api_base}/models", node)
    except Exception:  # noqa: BLE001 - any failure to answer is down
        return False, set()
    return status < 400, set(ids)


def _get_models(url: str, node: Node) -> tuple[int, set]:
    import httpx
    key = secret(node)
    transport = httpx.HTTPTransport(local_address="0.0.0.0") if node.ipv4 else None
    with httpx.Client(transport=transport,
                      timeout=httpx.Timeout(node.timeout, connect=node.connect_timeout)) as c:
        r = c.get(url, headers={"Authorization": f"Bearer {key}"} if key else {})
    try:
        ids = {str(m.get("id")) for m in r.json().get("data") or [] if isinstance(m, dict)}
    except ValueError:
        ids = set()
    return r.status_code, ids


def _ask(gateway: str, key: str, model: str, timeout: float):
    import httpx
    from harness import purpose
    tag = {purpose.HEADER: purpose.TAG_PREFIX + purpose.SMOKE}
    return httpx.post(f"{gateway.rstrip('/')}/v1/chat/completions",
                      headers={**({"Authorization": f"Bearer {key}"} if key else {}), **tag},
                      timeout=timeout,
                      json={"model": model, "max_tokens": 4,
                            "messages": [{"role": "user", "content": "Reply with exactly: OK"}]})


def smoke(gateway: str, key: str, nodes: list[Node], get=_get_models, ask=_ask, clock=None) -> list[tuple[bool, str]]:
    """(passed, line) per node model: up, the node answers through the gateway; down, this machine does, fast."""
    import time
    clock = clock or time.monotonic
    out = []
    for node in nodes:
        if unidentified(node):
            out.append((False, unidentified(node)))
        up, ids = _probe(node, get)
        for model in node.models:
            if up and node.node_id(model) not in ids:
                out.append((False, f"node {node.name} up but does not advertise "
                                   f"{node.node_id(model)} for {model}; it lists "
                                   f"{', '.join(sorted(ids)) or 'nothing'} (set `as:` in nodes.yaml)"))
                continue
            started = clock()
            try:
                r = ask(gateway, key, model, node.timeout + 30)
            except Exception as exc:  # noqa: BLE001
                out.append((False, f"node {node.name} {model}: gateway did not answer ({exc})"))
                continue
            took = clock() - started
            served_by = r.headers.get("x-sohot-node", "")
            fell = r.headers.get("x-sohot-fallback", "")
            if not up and r.status_code == 503 and NO_LOCAL_COPY in getattr(r, "text", ""):
                out.append((took <= node.connect_timeout + 10,
                            f"node {node.name} down: {model} refused in {took:.1f}s, {NO_LOCAL_COPY} it"))
            elif r.status_code >= 400:
                out.append((False, f"node {node.name} {model}: HTTP {r.status_code}"))
            elif up and served_by == node.name and node.fingerprint \
                    and r.headers.get("x-sohot-machine", "") != node.identity:
                out.append((False, f"node {node.name} up: {model} served by {served_by}, but the gateway "
                                   f"names its machine {r.headers.get('x-sohot-machine') or 'nothing'}, "
                                   f"not {node.identity}; restart the gateway to reload nodes.yaml"))
            elif up:
                out.append((served_by == node.name,
                            f"node {node.name} up: {model} served by "
                            f"{served_by or r.headers.get('x-sohot-machine', 'this machine')}"))
            else:
                fast = took <= node.connect_timeout + 10
                out.append((not served_by and fell == node.name and fast,
                            f"node {node.name} down: {model} fell back to this machine in "
                            f"{took:.1f}s (fallback header {fell or 'missing'})"))
    return out


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m harness.nodes")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("exports", help="shell exports of each node's Keychain key, for serve-gateway.sh")
    sub.add_parser("show", help="the nodes this machine routes to")
    sub.add_parser("check", help="fail each node with no machine fingerprint")
    sub.add_parser("fingerprint", help="this machine's fingerprint, for `machine:` where it serves as a node")
    s = sub.add_parser("smoke", help="ask the gateway for each node's models; node up and node down")
    s.add_argument("--gateway", required=True)
    args = p.parse_args(argv)
    if args.cmd == "fingerprint":
        from evals import environment
        print(environment.identity()["fingerprint"])
        return 0
    nodes = load()
    if args.cmd == "check":
        bad = [why for why in map(unidentified, nodes) if why]
        for why in bad:
            print(f"FAIL  {why}")
        for n in nodes:
            if not unidentified(n):
                print(f"PASS  node {n.name} is {n.identity}")
        return 1 if bad else 0
    if args.cmd == "exports":
        print("\n".join(exports(nodes)))
        return 0
    if args.cmd == "show":
        for n in nodes:
            held = ",".join(m if n.node_id(m) == m else f"{m} as {n.node_id(m)}" for m in n.models)
            print(f"{n.name}\t{n.engine}\t{held}\tconnect {n.connect_timeout:g}s "
                  f"timeout {n.timeout:g}s cooldown {n.cooldown:g}s\tkey {n.key or 'none'}")
        return 0
    from harness import gateway_key
    rows = smoke(args.gateway, gateway_key.key(), nodes)
    for passed, line in rows:
        print(f"{'PASS' if passed else 'FAIL'}  {line}")
    if not rows:
        print("SKIP  no serving nodes in " + str(path()))
    return 0 if all(p for p, _ in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
