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
#: A node's preset tags each model with the sha256 of the file it serves, so its /v1/models names it. #1683.
DIGEST_TAG = "sha256:"
#: The Studio's record of what each node reported, in $LOCALHARNESS_HOME; nodes.yaml stays the owner's.
RECORD = "node-digests.json"
#: How long reading a node's /v1/models for its digests may take; its own timeout covers a cold reply.
DIGEST_TIMEOUT_S = 10.0

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
_SHA = re.compile(r"^[0-9a-f]{64}$")
_KEY = re.compile(r"^(env:[A-Za-z_][A-Za-z0-9_]*|keychain:[^/\s]+/[^/\s]+)$")
_SSH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*(@[A-Za-z0-9_][A-Za-z0-9._-]*)?$")
ROLES = ("interactive", "node")


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
    #: Kept in nodes.yaml but left out of routing, fallbacks, probes and checks. #1061.
    parked: bool = False
    #: An interactive node: only these lanes' sohot-<lane> aliases go to it, never its models by name. #1562.
    lanes: tuple[str, ...] = ()
    #: (gateway id, sha256 of the GGUF the node serves it from), from a models entry's sha256:. #1652.
    digests: tuple[tuple[str, str], ...] = ()
    #: `deploy:` in nodes.yaml: the ssh destination, key, checkout and LH_ROLE a Studio deploy installs it with. #1692.
    ssh: str = ""
    ssh_key: str = ""
    deploy_dir: str = ""
    role: str = ""

    def sha256(self, model: str) -> str:
        """The sha256 nodes.yaml records for a model, by its gateway id or the id the node is sent; "" for none."""
        want = model.lower()
        return next((sha for gid, sha in self.digests if want in (gid.lower(), self.node_id(gid).lower())), "")

    def takes(self, name: str) -> bool:
        """Whether a gateway entry by this name may go to this node."""
        from harness import gateway
        return not self.lanes or name.lower() in {gateway.LANE_ALIAS.format(lane) for lane in self.lanes}

    def asked(self) -> tuple[str, ...]:
        """The gateway names smoke asks for this node: its lane aliases, else its models."""
        from harness import gateway
        return tuple(gateway.LANE_ALIAS.format(lane) for lane in self.lanes) or self.models

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
        models, renamed, digests = [], [], []
        for m in raw.get("models") or []:
            if isinstance(m, dict):
                gid, sha = str(m.get("id") or "").strip(), str(m.get("sha256") or "").strip().lower()
                nid = str(m.get("as") or "").strip() or (gid if sha else "")
                if sha and not _SHA.match(sha):
                    raise ValueError(f"{at}: models {gid!r} sha256 must be 64 hex digits")
                if gid and nid:
                    models.append(gid)
                    if nid != gid:
                        renamed.append((gid, nid))
                    if sha:
                        digests.append((gid, sha))
                    continue
            elif isinstance(m, str) and m.strip():
                models.append(m.strip())
                continue
            models = []
            break
        if not models:
            raise ValueError(f"{at}: models must be a list of model ids, or of {{id, as, sha256}} where the "
                             f"node advertises a model under another id or its file's sha256 is recorded")
        parked = raw.get("parked", False)
        if not isinstance(parked, bool):
            raise ValueError(f"{at}: parked must be true or false")
        from harness import interactive
        lanes = raw.get("lanes") or []
        if not isinstance(lanes, list) or any(str(lane) not in interactive.LANES for lane in lanes):
            raise ValueError(f"{at}: lanes must be a list of {', '.join(interactive.LANES)}, not {lanes!r}")
        key = str(raw.get("key") or "").strip()
        if key and not _KEY.match(key):
            raise ValueError(f"{at}: key must be env:<VAR> or keychain:<service>/<account>, "
                             f"never the key itself")
        ssh, ssh_key, deploy_dir, role = _deploy(raw.get("deploy"), lanes, at)
        out.append(Node(name, base if base.endswith("/v1") else base + "/v1", engine,
                        tuple(models), key,
                        str(raw.get("machine") or "").strip(),
                        _number(raw, "connect_timeout", CONNECT_TIMEOUT_S, at),
                        _number(raw, "timeout", TIMEOUT_S, at),
                        _number(raw, "cooldown", COOLDOWN_S, at),
                        bool(raw.get("ipv4", True)), tuple(renamed), parked,
                        tuple(dict.fromkeys(str(lane) for lane in lanes)), tuple(digests),
                        ssh, ssh_key, deploy_dir, role))
    return out


def _deploy(raw, lanes: list, at: str) -> tuple[str, str, str, str]:
    """(ssh, key, dir, role) from a node's `deploy:` mapping; ("", ...) when it has none, so no deploy reaches it. #1692."""
    if raw is None:
        return "", "", "", ""
    if not isinstance(raw, dict):
        raise ValueError(f"{at}: deploy must be a mapping of ssh, key, dir and role")
    ssh = str(raw.get("ssh") or "").strip()
    if not _SSH.match(ssh):
        raise ValueError(f"{at}: deploy ssh {ssh!r} must be host or user@host (or a ~/.ssh/config Host)")
    role = str(raw.get("role") or ("interactive" if lanes else "node")).strip()
    if role not in ROLES:
        raise ValueError(f"{at}: deploy role must be one of {', '.join(ROLES)}, not {role!r}")
    return ssh, str(raw.get("key") or "").strip(), str(raw.get("dir") or "").strip(), role


def _all(file=None) -> list[Node]:
    import yaml
    where = Path(file) if file else path()
    try:
        text = where.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return parse(yaml.safe_load(text) or {}, str(where))


def load(file=None) -> list[Node]:
    """This machine's serving nodes, parked ones left out; [] when it has no nodes.yaml."""
    return [n for n in _all(file) if not n.parked]


def parked(file=None) -> list[Node]:
    """The nodes nodes.yaml keeps but marks `parked: true`. #1061."""
    return [n for n in _all(file) if n.parked]


def parked_names(file=None) -> list[str]:
    """Parked node names; [] when nodes.yaml is missing or malformed, for reports that must not fail on it."""
    try:
        return [n.name for n in parked(file)]
    except ValueError:
        return []


def parked_lines(names: list[str]) -> list[str]:
    return [f"PARK  node {n} is parked (parked: true in {path()}): not routed, probed or checked" for n in names]


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
    entries, twins, fallbacks, held = [], [], [], set()
    for entry in data.get("model_list") or []:
        params = entry.get("litellm_params") or {}
        model = gateway.strip_provider(str(params.get("model", "")))
        node = next((n for n in nodes if model.lower() in {m.lower() for m in n.models}
                     and n.takes(str(entry.get("model_name", "")))), None)
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
    for node in (n for n in nodes if not n.lanes):
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


def _get_models(url: str, node: Node, timeout: float | None = None) -> tuple[int, dict]:
    """(HTTP status, {advertised id: its tags})."""
    import httpx
    key = secret(node)
    transport = httpx.HTTPTransport(local_address="0.0.0.0") if node.ipv4 else None
    with httpx.Client(transport=transport,
                      timeout=httpx.Timeout(timeout or node.timeout, connect=node.connect_timeout)) as c:
        r = c.get(url, headers={"Authorization": f"Bearer {key}"} if key else {})
    try:
        ids = {str(m.get("id")): tuple(m.get("tags") or ()) for m in r.json().get("data") or []
               if isinstance(m, dict)}
    except (ValueError, AttributeError):
        ids = {}
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
        missing = [m for m in node.models if up and node.node_id(m) not in ids]
        for model in missing:
            out.append((False, f"node {node.name} up but does not advertise "
                               f"{node.node_id(model)} for {model}; it lists "
                               f"{', '.join(sorted(ids)) or 'nothing'} (set `as:` in nodes.yaml)"))
        for model in node.asked():
            if model in missing:
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


def _get_build(node: Node) -> str:
    import httpx
    from harness import context
    key = secret(node)
    transport = httpx.HTTPTransport(local_address="0.0.0.0") if node.ipv4 else None
    with httpx.Client(transport=transport,
                      timeout=httpx.Timeout(node.timeout, connect=node.connect_timeout)) as c:
        r = c.get(f"{node.api_base.rstrip('/').removesuffix('/v1')}/props",
                  headers={"Authorization": f"Bearer {key}"} if key else {})
    return context.build_of(r.json().get("build_info")) if r.status_code < 400 else ""


def builds(nodes: list[Node], here: str, get=None) -> list[tuple[bool, str]]:
    """(same build, line) per node: its llama.cpp build beside this machine's; a mismatch warns. #1607."""
    get = get or _get_build
    out = []
    for node in nodes:
        try:
            got = get(node)
        except Exception:  # noqa: BLE001 - a node that does not answer has no build to compare
            got = ""
        if not got:
            out.append((False, f"node {node.name} names no llama.cpp build in its /props; "
                               f"its replies and receipts carry none"))
        elif here and got != here:
            out.append((False, f"node {node.name} runs llama.cpp build {got}, this machine {here}: "
                               f"its replies and receipts name {got}"))
        else:
            out.append((True, f"node {node.name} runs llama.cpp build {got}, this machine {here or 'none'}"))
    return out


def lan_bound(environ=None) -> bool:
    """Whether this machine's llama-server answers another machine, read from LLAMACPP_HOST at call time."""
    from harness import serving
    environ = os.environ if environ is None else environ
    return (environ.get("LLAMACPP_HOST") or "127.0.0.1").strip().strip("[]") not in serving.LOOPBACK


def _knows_tags(binary: str = "") -> bool:
    import subprocess

    from harness import serving
    binary = binary or serving.llamacpp_binary() or ""
    if not binary:
        return False
    try:
        out = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return "--tags" in out.stdout + out.stderr


def tag_digests(rows: list[dict], environ=None, knows=None) -> list[dict]:
    """Preset rows with each served file's sha256 when a LAN node's llama-server can tag it, for /v1/models. #1683."""
    if not rows or not lan_bound(environ) or not (knows or _knows_tags)():
        return rows
    from harness import identity
    out = []
    for row in rows:
        try:
            sha = identity.file_digest(row["path"]) if row.get("path") and row.get("ctx") else ""
        except OSError:
            sha = ""
        out.append({**row, "sha256": sha} if sha else row)
    return out


def record_path() -> Path:
    """The node-reported digests the Studio records itself, beside nodes.yaml and never in it. #1683."""
    from harness import paths
    return paths.home() / RECORD


def _records() -> dict:
    import json
    try:
        got = json.loads(record_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def recorded(node: Node, model: str) -> str:
    """The sha256 this node last reported for a model, "" when it reported none or was another machine then."""
    got = _records().get(node.name) or {}
    if not isinstance(got, dict) or got.get("machine") != node.identity:
        return ""
    return str((got.get("models") or {}).get(node.node_id(model)) or "")


def digest(node: Node, model: str) -> tuple[str, str]:
    """(sha256, "") from nodes.yaml or what the node reported, else ("", why there is none or they disagree)."""
    mine, got = node.sha256(model), recorded(node, model)
    if mine and got and mine != got:
        return "", (f"{path().name} records sha256 {mine} for {model} on node {node.name}, "
                    f"but the node reports {got}")
    if mine or got:
        return mine or got, ""
    return "", (f"{path().name} records no sha256 for {model} on node {node.name}, and the node has "
                f"reported none to {record_path()}")


def _record(node: Node, reported: dict) -> None:
    import datetime
    import json
    got = _records()
    got[node.name] = {"machine": node.identity, "models": reported,
                      "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    where = record_path()
    where.parent.mkdir(parents=True, exist_ok=True)
    tmp = where.with_name(where.name + ".tmp")
    tmp.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, where)


def _reported(tags) -> str:
    return next((t[len(DIGEST_TAG):].lower() for t in tags or () if isinstance(t, str) and t.startswith(DIGEST_TAG)
                 and _SHA.match(t[len(DIGEST_TAG):].lower())), "")


def digests(nodes: list[Node], get=None) -> list[tuple[str, str]]:
    """(PASS|FAIL|WARN, line) per node model: the sha256 its /v1/models tags, recorded, and checked against nodes.yaml. #1683."""
    get = get or (lambda url, node: _get_models(url, node, DIGEST_TIMEOUT_S))
    out = []
    for node in nodes:
        try:
            status, ids = get(f"{node.api_base}/models", node)
        except Exception as exc:  # noqa: BLE001 - a node that does not answer has no digest to read
            status, ids, why = 0, {}, f"no answer ({type(exc).__name__})"
        else:
            why = f"HTTP {status}" if status >= 400 else ""
        if why:
            out.append(("WARN", f"node {node.name} did not answer /v1/models ({why}): no sha256 read or "
                                f"recorded for {', '.join(node.models)}"))
            continue
        tags = ids if isinstance(ids, dict) else dict.fromkeys(ids, ())
        reported = {}
        for model in node.models:
            nid = node.node_id(model)
            got, mine = _reported(tags.get(nid)), node.sha256(model)
            if not got:
                out.append(("WARN", f"node {node.name} reports no sha256 for {nid} (its release or preset tags "
                                    f"none){'' if mine else '; its runs carry no model digest'}"))
                continue
            reported[nid] = got
            if mine and mine != got:
                out.append(("FAIL", f"node {node.name} {model}: {path().name} records sha256 {mine}, "
                                    f"the node reports {got}"))
            elif mine:
                out.append(("PASS", f"node {node.name} {model}: sha256 {got} matches {path().name}"))
            else:
                out.append(("PASS", f"node {node.name} {model}: sha256 {got} reported, recorded in {record_path()}"))
        _record(node, reported)
    return out


def digest_lines(models) -> list[str]:
    """`- {id: <stem>, sha256: <hex>}` per GGUF, the models entry that gives a node-served model an identity. #1652."""
    from harness import gguf, identity
    out = []
    for m in models:
        path = Path(m).expanduser()
        path = path if path.suffix == ".gguf" else gguf.models_dir() / f"{m}.gguf"
        out.append(f"- {{id: {path.stem}, sha256: {identity.file_digest(path)}}}")
    return out


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m harness.nodes")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("exports", help="shell exports of each node's Keychain key, for serve-gateway.sh")
    sub.add_parser("show", help="the nodes this machine routes to")
    sub.add_parser("check", help="fail each node with no machine fingerprint or a sha256 its node contradicts")
    sub.add_parser("fingerprint", help="this machine's fingerprint, for `machine:` where it serves as a node")
    d = sub.add_parser("digest", help="models lines with each GGUF's sha256, for nodes.yaml where it serves as a node")
    d.add_argument("models", nargs="+", help="a GGUF path, or a stem in this machine's models dir")
    s = sub.add_parser("smoke", help="ask the gateway for each node's models; node up and node down")
    s.add_argument("--gateway", required=True)
    args = p.parse_args(argv)
    if args.cmd == "fingerprint":
        from evals import environment
        print(environment.identity()["fingerprint"])
        return 0
    if args.cmd == "digest":
        for line in digest_lines(args.models):
            print(line)
        return 0
    nodes = load()
    rested = [n.name for n in parked()] if args.cmd in ("check", "show", "smoke") else []
    for line in parked_lines(rested):
        print(line)
    if args.cmd == "check":
        bad = [why for why in map(unidentified, nodes) if why]
        for why in bad:
            print(f"FAIL  {why}")
        for n in nodes:
            if not unidentified(n):
                print(f"PASS  node {n.name} is {n.identity}")
        shas = digests(nodes)
        for status, line in shas:
            print(f"{status}  {line}")
        return 1 if bad or any(s == "FAIL" for s, _ in shas) else 0
    if args.cmd == "exports":
        print("\n".join(exports(nodes)))
        return 0
    if args.cmd == "show":
        for n in nodes:
            held = ",".join(m if n.node_id(m) == m else f"{m} as {n.node_id(m)}" for m in n.models)
            held += f"\tlanes {','.join(n.lanes)} only" if n.lanes else ""
            print(f"{n.name}\t{n.engine}\t{held}\tconnect {n.connect_timeout:g}s "
                  f"timeout {n.timeout:g}s cooldown {n.cooldown:g}s\tkey {n.key or 'none'}")
        return 0
    from harness import gateway_key
    rows = smoke(args.gateway, gateway_key.key(), nodes)
    for passed, line in rows:
        print(f"{'PASS' if passed else 'FAIL'}  {line}")
    from harness import serving
    for same, line in builds(nodes, serving.llamacpp_build()):
        print(f"{'PASS' if same else 'WARN'}  {line}")
    shas = digests(nodes)
    for status, line in shas:
        print(f"{status}  {line}")
    if not rows and not rested:
        print("SKIP  no serving nodes in " + str(path()))
    return 0 if all(p for p, _ in rows) and all(s != "FAIL" for s, _ in shas) else 1


if __name__ == "__main__":
    raise SystemExit(main())
