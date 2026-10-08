"""`soh benchmarks`: found benchmark sources, their contamination status, and what was imported. #491, #470."""
from __future__ import annotations

import time

from harness.commands.common import emit, err, note


def _lanes(a) -> list[str] | None:
    lane = (getattr(a, "lane", "") or "").strip().lower()
    return [lane] if lane else None


def _counts(lane: str, scope) -> bool:
    """A failed source in scope counts; one for a lane with no queries is the #601 KeyError's leftover."""
    from harness import benchmarks as bm
    return lane in bm.LANE_QUERIES and (scope is None or lane in scope)


def sweep_report(a) -> int:
    """The discover loop's benchmark tier: one sweep per interval, then a count per lane."""
    from harness import benchmarks as bm
    from harness import memory_store as ms
    conn = ms.connect()
    started = time.time()
    try:
        found = bm.sweep(conn, lanes=_lanes(a), force=bool(getattr(a, "force", False)))
        scope = _lanes(a)
        failed = [(r["name"], r["last_error"]) for r in conn.execute(
            "SELECT name, last_error FROM sources WHERE kind = ? AND last_status = 'failed' "
            "ORDER BY name", (bm.KIND,))
                  if _counts(r["name"].rpartition(":")[2], scope)]
        deferred = [r["name"] for r in conn.execute(
            "SELECT name FROM sources WHERE kind = ? AND last_status = ? AND last_attempt_at >= ? "
            "ORDER BY name", (bm.KIND, ms.DEFERRED, started))]
    finally:
        conn.close()
    by: dict[str, int] = {}
    for b in found:
        by[b.lane] = by.get(b.lane, 0) + 1
    for lane in sorted(by):
        note(f"  {lane:8} {by[lane]} benchmark sources read")
    for name in deferred:
        note(f"  rate-limited {name}: deferred to the next sweep")
    if not found and not deferred:
        note("  no benchmark source was due; the sweep runs once per discovery interval")
    if scope and scope[0] not in bm.LANE_QUERIES:
        note(f"  the {scope[0]} lane has no benchmark queries, so there is nothing to read")
    for name, why in failed:
        note(f"  FAILED {name}: {why or 'no error recorded'}")
    emit(not failed, found=by, failed=[name for name, _ in failed])
    return 1 if failed else 0


def _training(a, conn) -> int:
    from harness import benchmarks as bm
    from harness import memory_store as ms
    for spec in a.training:
        repo, _, alias = spec.partition("=")
        try:
            facts = bm.read_training(repo, readme_get=_readme)
        except Exception as exc:  # noqa: BLE001
            return err(f"{repo}: {exc}")
        ms.set_training(conn, repo, alias=alias, lane=(a.lane or "").strip().lower(), **facts)
        note(f"  {repo}: cutoff {facts['cutoff'] or 'unknown'} ({facts['cutoff_source']}), "
             f"{len(facts['datasets'])} declared datasets")
    return 0


def _readme(repo: str) -> str:
    try:
        import httpx
        r = httpx.get(f"https://huggingface.co/{repo}/raw/main/README.md", timeout=30,
                      follow_redirects=True)
        return r.text if r.status_code == 200 else ""
    except Exception:  # noqa: BLE001
        return ""


def _probe(a, conn) -> int:
    from evals import run as evals_run
    from harness import contamination as ct
    from harness import memory_store as ms
    lane = (a.lane or "decide").strip().lower()
    cases = [c for c in evals_run.load_cases(_cases_root() / lane) if c.modality == lane]
    if a.limit:
        cases = cases[:a.limit]
    ask = ct.gateway_ask(a.gateway)
    for model in a.probe:
        rows = ct.probe(conn, model, cases, ask, lane=lane)
        hits = sum(r["outcome"] == "hit" for r in rows)
        probed = sum(r["outcome"] in ("hit", "miss") for r in rows)
        note(f"  {model}: {hits}/{probed} probed cases reproduced verbatim "
             f"({len(rows) - probed} skipped or errored)")
    emit(summary=ms.probe_summary(conn, lane))
    return 0


def _cases_root():
    from evals import benchmark_import as bi
    return bi.CASES


def _listing(a, conn) -> int:
    from evals import benchmark_import as bi
    from harness import benchmarks as bm
    from harness import contamination as ct
    from harness import memory_store as ms
    lane = (a.lane or "").strip().lower()
    training = ms.training(conn)
    imported = bi.imported(_cases_root())
    sources = []
    fields = bm.Benchmark.__dataclass_fields__
    known = [bm.Benchmark(**{k: r[k] for k in fields}) for r in ms.benchmarks(conn)]
    for row in ms.benchmarks(conn, lane):
        b = bm.Benchmark(**{k: row[k] for k in fields})
        status, why = bm.contamination(b, training, known)
        sources.append({**b.as_dict(), "contamination": status, "why": why,
                        "imported": imported.get(b.name, {}).get(b.lane, 0),
                        "converter": b.name in bi.IMPORTERS, "first_seen": row["first_seen"],
                        "last_seen": row["last_seen"]})
    found = {s["name"] for s in sources}
    unlisted = {name: by for name, by in imported.items() if name not in found
                and (not lane or lane in by)}
    probes = ms.probe_summary(conn, lane)
    overlap = ct.with_and_without(conn, lane, _cases_root()) if lane else []
    emit(sources=sources, training=training, imported=imported, probes=probes,
         with_and_without=overlap)
    for s in sources:
        note(f"{s['lane']:7} {s['name']:55} {s['created'] or '?':10} "
             f"{s['license'] or 'no license':12} {s['gated'] or 'open':6} "
             f"{s['task_format'] or '-':20} {s['contamination']:12} imported {s['imported']}")
    for name, by in sorted(unlisted.items()):
        note(f"imported, not swept: {name} {by}")
    for t in training:
        note(f"cutoff  {t['candidate']} ({t['alias'] or 'no alias'}): {t['cutoff'] or '?'} "
             f"from {t['cutoff_source'] or '?'}, {len(t['datasets'])} declared datasets")
    for p in probes:
        note(f"probe   {p['model']} {p['lane']}/{p['family']}: {p['hits']}/{p['probed']} "
             f"verbatim, mean overlap {p['mean_overlap'] or 0:.2f}, {p['skipped']} skipped "
             f"(a miss is not proof of absence)")
    for o in overlap:
        note(f"score   {o['candidate']}: {o['all']} on {o['n_all']} cases, {o['clean']} on "
             f"{o['n_clean']} without the {len(o['overlapping'])} it trained on")
    if not sources:
        note("no benchmark sources recorded; `soh benchmarks --sweep` reads the registries")
    return 0


def cmd_benchmarks(a) -> int:
    from evals import benchmark_import as bi
    from harness import memory_store as ms
    if getattr(a, "sweep", False):
        return sweep_report(a)
    if getattr(a, "import_source", ""):
        if not a.n:
            return err("--import needs --n")
        try:
            written = bi.import_benchmark(a.import_source, a.n)
        except ValueError as exc:
            return err(str(exc))
        note(f"{len(written)} cases imported from {a.import_source}")
        emit(written=[str(p) for p in written])
        return 0 if written else 1
    conn = ms.connect()
    try:
        if getattr(a, "training", None):
            return _training(a, conn) or _listing(a, conn)
        if getattr(a, "probe", None):
            return _probe(a, conn)
        return _listing(a, conn)
    finally:
        conn.close()
