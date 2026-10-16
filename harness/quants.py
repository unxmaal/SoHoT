"""Follow a base model too big or unloadable here to its quantized repos. #882."""
from __future__ import annotations

import json
import re
import time
from urllib.parse import quote

from harness import inspect as ins, reasons
from harness import memory_store as ms

QUANTIZERS = ("unsloth", "bartowski", "lmstudio-community", "mlx-community")
HF_API = "https://huggingface.co/api/models"
LISTING = HF_API + "?filter=base_model:quantized:{base}&sort=downloads&direction=-1&limit=50"
BY_AUTHOR = HF_API + "?author={author}&search={name}&sort=downloads&direction=-1&limit=10"
SEARCH = HF_API + "?search={name}&sort=downloads&direction=-1&limit=20"
README = "https://huggingface.co/{model_id}/raw/main/README.md"
#: Descendants inspected per base before giving up; each is one registry call.
TRIES = 4
SOURCE = "quants"
RELATION = "quantized"
#: A repo of this name is a finetune that was then quantized, not the base's own weights.
DERIVED = re.compile(r"abliterat|uncensor|heretic|distill|merge|lora|nsfw|roleplay|sangreal", re.I)
#: A format suffix on a repo name: what is left is the model it packages.
FORMAT_SUFFIX = re.compile(r"(-(gguf|mlx|awq|gptq|fp8|nvfp4|mxfp4|[0-9]+bit|bf16|q[0-9]\w*))+$", re.I)
#: A table header naming a model carries a parameter count: 35B, A3B, 0.8B.
_PARAMS = re.compile(r"(^|[-_])a?[0-9]+(\.[0-9]+)?[bm]($|[-_])", re.I)
_MODEL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._]*(-[A-Za-z0-9._]+)+$")
_TH = re.compile(r"<th[^>]*>(.*?)</th>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _id(row: dict) -> str:
    return str(row.get("id") or row.get("modelId") or "")


def _get(url: str, get) -> str:
    from harness import feeds
    try:
        return (get or ins.hf_get)(url)
    except feeds.RateLimitedFeed as exc:
        raise ins.Deferred(f"{url}: rate-limited (HTTP 429)") from exc


def _rows(url: str, get) -> list[dict]:
    try:
        got = json.loads(_get(url, get))
    except ins.Deferred:
        raise
    except Exception:  # noqa: BLE001 - an unreadable listing lists nothing
        return []
    return [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []


def runtime_of(model_id: str, row: dict) -> str:
    """The runtime a quantized repo's weights load in, or "" for a format this project cannot serve."""
    if ins.is_gguf(model_id, row):
        return "llamacpp"
    tags = {str(t).lower() for t in row.get("tags") or []}
    if (row.get("library_name") or "").lower() == "mlx" or "mlx" in tags:
        return "mlx"
    return ""


def ranked(base: str, rows: list[dict], machine=None) -> list[str]:
    """Descendants that package the base itself in a runtime here: known quantizers first, then downloads."""
    want = _norm(base.split("/")[-1])
    keep = []
    for r in rows:
        rid = _id(r)
        repo = rid.split("/")[-1]
        if not rid or rid == base or want not in _norm(repo) or DERIVED.search(repo):
            continue
        rt = runtime_of(rid, r)
        if not rt or (machine is not None and machine.refuses(rt)):
            continue
        if rid not in [_id(k) for k in keep]:
            keep.append(r)
    keep.sort(key=lambda r: (_id(r).split("/")[0].lower() not in QUANTIZERS,
                             -int(r.get("downloads") or 0)))
    return [_id(r) for r in keep]


def descendants(base: str, get=None, machine=None) -> list[str]:
    """The base's quantized repos from its base_model:quantized listing, else from the known quantizers."""
    found = ranked(base, _rows(LISTING.format(base=base), get), machine)
    if found:
        return found
    name = quote(base.split("/")[-1])
    rows = [r for author in QUANTIZERS
            for r in _rows(BY_AUTHOR.format(author=author, name=name), get)]
    return ranked(base, rows, machine)


def best(base: str, *, get=None, ceiling: int | None = None, machine=None,
         skip=frozenset()) -> ins.Fit | None:
    """The first ranked descendant whose card fits this machine, or None."""
    for rid in [d for d in descendants(base, get, machine) if d not in skip][:TRIES]:
        try:
            fit = ins.inspect_model(rid, fetch=get, ceiling=ceiling, machine=machine)
        except (ins.Gone, ins.InspectError):
            continue
        if fit.verdict == "fits":
            return fit
    return None


def followed(conn, base: str) -> str:
    """A live descendant this path already proposed for the base, or ""."""
    row = conn.execute(
        "SELECT d.name FROM edges e JOIN proposals s ON s.id = e.src "
        "JOIN proposals d ON d.id = e.dst WHERE s.name = ? AND e.relation = ? "
        f"AND d.state NOT IN ({','.join('?' * len(ms.TERMINAL))}) ORDER BY e.id LIMIT 1",
        (base, RELATION, *ms.TERMINAL)).fetchone()
    return row["name"] if row else ""


def _lane_of(conn, name: str) -> str:
    row = conn.execute("SELECT lane FROM proposals WHERE name = ?", (name,)).fetchone()
    return (row["lane"] or "") if row else ""


def propose(conn, base: str, fit: ins.Fit) -> str:
    """Record and queue a fitting descendant, linked to its base."""
    lane = fit.lanes.get(fit.repo) or _lane_of(conn, base)
    ms.record(conn, ms.Seen(
        name=fit.repo, source=SOURCE, registry=ms.HUGGINGFACE, kind="weights",
        category=ms.MODEL, url=f"https://huggingface.co/{fit.repo}", resolved=fit.repo,
        lane=lane, why=f"quantized from {base}", lane_source=fit.card.lane_source,
        description=fit.description))
    ms.set_size(conn, fit.repo, fit.largest)
    ms.set_card(conn, fit.repo, fit.card)
    if conn.execute("SELECT 1 FROM proposals WHERE name = ?", (base,)).fetchone():
        ms.link(conn, base, fit.repo, RELATION)
    try:
        ms.decide(conn, fit.repo, "queued", tier=ms.INSPECT, size_bytes=fit.largest,
                  reason=reasons.CANDIDATE, detail=f"fits: quantized from {base}: {fit.why}"[:200])
    except ms.IllegalTransition as exc:
        return f"    {base}: {fit.repo} kept its state: {exc}"
    return f"    {base}: proposed {fit.repo} ({fit.largest / ins.GIB:.1f} GiB)"


def follow(conn, base: str, *, get=None, ceiling: int | None = None, machine=None) -> str:
    """Propose the base's best-fitting quantized repo unless one is already live."""
    live = followed(conn, base)
    if live:
        return f"    {base}: already followed to {live}"
    fit = best(base, get=get, ceiling=ceiling, machine=machine, skip=ms.settled(conn))
    if fit is None:
        return f"    {base}: no quantized repo fits here"
    return propose(conn, base, fit)


def compared(readme: str, own: str = "") -> list[str]:
    """Model names a card's comparison tables head their columns with."""
    cells = [_TAG.sub("", c) for c in _TH.findall(readme or "")]
    lines = (readme or "").splitlines()
    for i, line in enumerate(lines[:-1]):
        if line.strip().startswith("|") and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            cells += line.strip().strip("|").split("|")
    out = []
    for c in (x.replace("*", "").strip() for x in cells):
        if (_MODEL_NAME.match(c) and _PARAMS.search(c) and _norm(c) != _norm(own)
                and c not in out):
            out.append(c)
    return out


def resolve(name: str, get=None) -> str:
    """The original (untyped-lineage) repo a model name means, exact name first, or ""."""
    want = _norm(name)
    hits = []
    for r in _rows(SEARCH.format(name=quote(name)), get):
        rid = _id(r)
        got = _norm(rid.split("/")[-1])
        if any(str(t).startswith("base_model:") for t in r.get("tags") or []):
            continue
        if got == want or got.startswith(want):
            hits.append((got != want, -int(r.get("downloads") or 0), rid))
    return min(hits)[2] if hits else ""


def family(model_id: str, card: dict) -> list[str]:
    """What a model is built from: its card's base_model parents, else its name less a format suffix."""
    parents = [p for p, _ in ins.lineage(card.get("tags") or [])]
    if parents:
        return parents
    org, _, repo = model_id.partition("/")
    bare = FORMAT_SUFFIX.sub("", repo)
    return [f"{org}/{bare}"] if bare and bare != repo else []


def incumbents(conn) -> list[str]:
    """The HuggingFace repos the adopted lane defaults on this machine were built from."""
    from harness import adopt
    out = []
    for row in adopt.current(conn).values():
        got = conn.execute(
            "SELECT p.name FROM candidates c JOIN proposals p ON p.id = c.proposal_id "
            "WHERE c.id = ? AND p.registry = ?", (row["candidate_id"], ms.HUGGINGFACE)).fetchone()
        if got and got["name"] not in out:
            out.append(got["name"])
    return out


def unrunnable(conn) -> list[str]:
    """Bases of HuggingFace proposals refused here for size or runtime: a quant's parent, else itself."""
    rows = conn.execute(
        "SELECT p.id, p.name FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
        "WHERE p.registry = ? AND p.state = 'declined' AND ("
        "(v.tier = ? AND (v.detail LIKE 'too-big%' OR v.detail LIKE 'needs-%')) "
        "OR (v.tier = ? AND v.reason = ?)) ORDER BY p.id",
        (ms.HUGGINGFACE, ms.INSPECT, ms.SCREEN, reasons.RUNTIME)).fetchall()
    out = []
    for r in rows:
        parent = conn.execute("SELECT parent FROM lineage WHERE proposal_id = ? AND kind = ? "
                              "ORDER BY id LIMIT 1", (r["id"], RELATION)).fetchone()
        base = parent["parent"] if parent else r["name"]
        if base not in out:
            out.append(base)
    return out


def seeds(conn, get=None) -> list[str]:
    """Each incumbent's family and the models its card compares itself with."""
    out: list[str] = []
    for inc in incumbents(conn):
        try:
            card = ins.hf_model(inc, fetch=get)
        except (ins.Gone, ins.InspectError):
            continue
        fam = family(inc, card)
        for model_id in [inc, *fam]:
            try:
                text = _get(README.format(model_id=model_id), get)
            except ins.Deferred:
                raise
            except Exception:  # noqa: BLE001 - a missing card names nothing
                continue
            for name in compared(text, model_id.split("/")[-1]):
                got = resolve(name, get)
                if got:
                    fam.append(got)
        for f in fam:
            if f not in out and f != inc:
                out.append(f)
    return out


def sweep(conn, *, get=None, ceiling: int | None = None, machine=None,
          now: float | None = None, force: bool = False) -> list[str]:
    """Follow every unrunnable base and every incumbent seed to a quant, once per discovery interval."""
    from harness import benchmarks
    now = time.time() if now is None else float(now)
    if not benchmarks._due(conn, SOURCE, now, force):
        return []
    lines = []
    try:
        bases = unrunnable(conn)
        for seed in seeds(conn, get):
            if seed not in bases:
                bases.append(seed)
        for base in bases:
            lines.append(_follow_seed(conn, base, get, ceiling, machine))
    except ins.Deferred as exc:
        ms.record_source(conn, SOURCE, kind=SOURCE, deferred=True, error=str(exc), at=now)
        return lines + [f"    registry rate-limited ({exc}); the rest wait for the next sweep"]
    ms.record_source(conn, SOURCE, kind=SOURCE, url=HF_API, at=now)
    return lines


def _follow_seed(conn, base, get, ceiling, machine) -> str:
    """A seed the store has not read is inspected and recorded first: it may fit as it is."""
    row = conn.execute("SELECT state FROM proposals WHERE name = ?", (base,)).fetchone()
    if row is not None:
        if row["state"] != "declined":
            return f"    {base}: {row['state']} as it is"
        return follow(conn, base, get=get, ceiling=ceiling, machine=machine)
    try:
        fit = ins.inspect_model(base, fetch=get, ceiling=ceiling, machine=machine)
    except (ins.Gone, ins.InspectError) as exc:
        return f"    {base}: {exc}"
    ms.record(conn, ms.Seen(
        name=base, source=SOURCE, registry=ms.HUGGINGFACE, kind="weights",
        category=ms.MODEL, url=f"https://huggingface.co/{base}", resolved=base,
        lane=fit.lanes.get(base, ""), why="named by an incumbent's card",
        lane_source=fit.card.lane_source, description=fit.description))
    ms.set_size(conn, base, fit.largest)
    ms.set_card(conn, base, fit.card)
    outcome = {"fits": "queued", "unknown": ""}.get(fit.verdict, "declined")
    if outcome:
        ms.decide_or_skip(conn, base, outcome, tier=ms.INSPECT,
                          size_bytes=fit.largest if outcome == "queued" else 0,
                          reason=ins.reason_of(fit), until=ins.until_of(fit),
                          detail=f"{fit.verdict}: {fit.why}"[:200])
    if fit.verdict == "fits":
        return f"    {base}: proposed as it is ({fit.largest / ins.GIB:.1f} GiB)"
    return follow(conn, base, get=get, ceiling=ceiling, machine=machine)
