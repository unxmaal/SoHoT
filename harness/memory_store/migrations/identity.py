"""Migration helpers that backfill state, registries, candidates, adoptions and retests."""
from __future__ import annotations

import json
import re

from harness.memory_store.revisit import resolved_run_paths
from harness.memory_store.schema import ADOPT, GITHUB, HUGGINGFACE, MEASURE, SCREEN
from harness.memory_store.transitions import RETEST_AFTER_SECONDS, retest_eligible


def backfill_adoptions(conn) -> int:
    """One adoptions row per adopt-tier `measured` verdict. #412.

    The lane is read from the detail prefix here, once; nothing reads it there
    again.
    """
    from harness import adopt, lanes
    n = 0
    for r in conn.execute(
            "SELECT v.id, v.detail, v.run_id, v.machine_id, v.decided_at, "
            "COALESCE(v.candidate_id, (SELECT MAX(c.id) FROM candidates c "
            "WHERE c.proposal_id = v.proposal_id)) AS cid FROM verdicts v "
            "WHERE v.tier = ? AND v.outcome = 'measured' AND v.id NOT IN "
            "(SELECT verdict_id FROM adoptions WHERE verdict_id IS NOT NULL) "
            "ORDER BY v.id", (ADOPT,)).fetchall():
        lane = lanes.canonical(str(r["detail"]).partition(":")[0])
        spec = conn.execute("SELECT spec FROM candidates WHERE id = ?",
                            (r["cid"],)).fetchone() if r["cid"] else None
        if not lane or not spec or adopt.is_reference(spec["spec"]):
            continue
        how = (adopt.BY_HAND if "preferred by hand" in str(r["detail"])
               else adopt.MEASURED)
        conn.execute(
            "INSERT INTO adoptions (lane, candidate_id, run_id, verdict_id, "
            "machine_id, how, adopted_at) VALUES (?,?,?,?,?,?,?)",
            (lane, r["cid"], r["run_id"], r["id"], r["machine_id"], how,
             float(r["decided_at"])))
        n += 1
    return n


def backfill_retests(conn) -> int:
    """Schedule a first retest for each eligible rejection already held. #431."""
    n = 0
    for r in conn.execute(
            "SELECT p.id, p.state, v.tier, v.until, v.decided_at FROM proposals p "
            "JOIN verdicts v ON v.id = p.state_verdict_id "
            "WHERE p.next_retest_at IS NULL AND p.retest_count = 0").fetchall():
        if retest_eligible(r["state"], r["tier"], r["until"]):
            conn.execute("UPDATE proposals SET next_retest_at = ? WHERE id = ?",
                         (float(r["decided_at"]) + RETEST_AFTER_SECONDS, r["id"]))
            n += 1
    return n


def _backfill_state(conn) -> None:
    """Each proposal's state from its newest verdict, as every reader had it."""
    conn.execute(
        "UPDATE proposals SET state_verdict_id = (SELECT MAX(v.id) "
        "FROM verdicts v WHERE v.proposal_id = proposals.id)")
    conn.execute(
        "UPDATE proposals SET state = COALESCE((SELECT v.outcome FROM verdicts v "
        "WHERE v.id = proposals.state_verdict_id), '')")
    conn.commit()


#: The shape `lh judge` stored before receipts carried specs: Engine.name. #337.
_ACESTEP_LABEL = re.compile(r"^(?:acestep:)?acestep/([^@,]+)(?:@(.*))?$")


def _legacy_spec(label: str) -> str:
    """A spec for a label an old writer stored in place of one; else as given."""
    m = _ACESTEP_LABEL.match(label or "")
    if not m:
        return label
    return f"acestep:{m.group(1)}" + (f",{m.group(2)}" if m.group(2) else "")


def _adopted_by_name(conn) -> list:
    """Proposals adopt.record created from a spec or a receipt key."""
    return conn.execute(
        "SELECT p.id, p.name, p.lane FROM proposals p WHERE EXISTS "
        "(SELECT 1 FROM sightings s WHERE s.proposal_id = p.id) AND NOT EXISTS "
        "(SELECT 1 FROM sightings s WHERE s.proposal_id = p.id "
        " AND s.source != 'adopt')").fetchall()


def backfill_candidates(conn, runs=None) -> dict:
    """Fill `candidates` from what the store and receipts already hold. #407.

    Never decides anything: verdict outcomes are untouched, and a verdict moved
    off a spec-named proposal never becomes its new proposal's latest row.
    """
    import json
    from harness import candidates as C, screen
    from harness.serving import LLAMACPP_PREFIX

    counts = {"gguf": 0, "proposals": 0, "receipt_specs": 0,
              "receipt_keys": 0, "run_path_confirmed": 0, "fakes": 0,
              "fakes_to_proposal": 0, "fakes_unresolved": 0,
              "verdicts_linked": 0}
    fakes = {r["id"]: dict(r) for r in _adopted_by_name(conn)}
    lane_of = {r["name"]: r["lane"] for r in conn.execute(
        "SELECT name, lane FROM proposals")}
    for d in conn.execute(
            "SELECT DISTINCT repo, file FROM downloads "
            "WHERE kind = 'gguf' AND file != '' ORDER BY repo").fetchall():
        repo, filename = d["repo"], d["file"]
        if repo in lane_of and str(filename).endswith(".gguf"):
            if C.ensure(conn, f"{LLAMACPP_PREFIX}{filename[:-len('.gguf')]}",
                        proposal=repo, lane=lane_of[repo]):
                counts["gguf"] += 1
    own = {}
    rows = conn.execute(
        "SELECT DISTINCT p.id, p.name, p.lane, p.attaches_to FROM proposals p "
        "JOIN verdicts v ON v.proposal_id = p.id "
        "WHERE v.tier IN (?, ?, ?)", (SCREEN, MEASURE, ADOPT)).fetchall()
    for r in rows:
        if r["id"] in fakes or not r["lane"]:
            continue
        try:
            spec = screen.candidate_for(r["lane"], r["name"],
                                        r["attaches_to"] or "", conn=conn)
        except Exception:  # noqa: BLE001
            spec = ""
        cid = C.ensure(conn, spec, proposal=r["name"], lane=r["lane"]) \
            if spec else None
        if cid:
            own[r["id"]] = cid
            counts["proposals"] += 1
    from harness import runs as R
    if runs is not None:
        R.backfill(conn, runs)
    for run in R.find(conn):
        specs = {k: _legacy_spec(v)
                 for k, v in json.loads(run["specs"] or "{}").items()}
        for key, spec in specs.items():
            if C.key_of(spec) == key and C.ensure(conn, spec, key=key,
                                                  lane=run["lane"]):
                counts["receipt_specs"] += 1
        for key in R.keys_in(conn, run["id"]):
            if key not in specs and ":" in key and C.key_of(key) == key \
                    and C.ensure(conn, key, lane=run["lane"]):
                counts["receipt_keys"] += 1
    for r in conn.execute(
            "SELECT DISTINCT v.proposal_id, v.run_path FROM verdicts v "
            "WHERE v.run_path != '' AND v.tier IN (?, ?)", (SCREEN, MEASURE)):
        cid = own.get(r["proposal_id"])
        run = next((R.at(conn, p) for p in resolved_run_paths(r["run_path"])
                    if R.at(conn, p)), None)
        if not cid or not run:
            continue
        key = conn.execute("SELECT receipt_key FROM candidates WHERE id = ?",
                           (cid,)).fetchone()[0]
        if key in R.keys_in(conn, run["id"]):
            counts["run_path_confirmed"] += 1
    _resolve_fakes(conn, fakes, counts)
    guessed = []
    for v in conn.execute(
            "SELECT v.id, v.proposal_id, v.run_id, v.tier, p.name, p.lane "
            "FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
            "WHERE v.candidate_id IS NULL AND v.tier IN (?, ?, ?) ORDER BY v.id",
            (SCREEN, MEASURE, ADOPT)).fetchall():
        cid, how = _candidate_from_receipt(conn, v, own.get(v["proposal_id"]))
        if cid is None:
            continue
        conn.execute("UPDATE verdicts SET candidate_id = ? WHERE id = ?",
                     (cid, v["id"]))
        counts["verdicts_linked"] += 1
        counts[f"verdicts_{how}"] = counts.get(f"verdicts_{how}", 0) + 1
        if how == "guessed":
            guessed.append({"verdict": v["id"], "proposal": v["name"],
                            "tier": v["tier"], "spec": conn.execute(
                                "SELECT spec FROM candidates WHERE id = ?",
                                (cid,)).fetchone()[0]})
    # What no receipt named was read off this machine's disk: say so. #506.
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('candidate_guesses', ?)",
                 (json.dumps(guessed, sort_keys=True),))
    conn.commit()
    return counts


def _candidate_from_receipt(conn, verdict, disk_cid) -> tuple:
    """(candidate id, how) for a pre-#407 verdict: its run's receipt first. #506.

    how is 'confirmed' (the disk's spec ran in the cited run), 'receipt' (the
    cited run has exactly one spec that can be this proposal's) or 'guessed'
    (no receipt says, so the spec is what this machine's disk resolves now).
    """
    from harness import adopt, candidates as C, screen, winners
    from harness import runs as R
    run = R.get(conn, verdict["run_id"]) if verdict["run_id"] else None
    if run is None:
        return disk_cid, "guessed"
    keys = R.keys_in(conn, run["id"])
    specs = {k: _legacy_spec(s) for k, s in json.loads(run["specs"] or "{}").items()}
    disk_key = conn.execute("SELECT receipt_key FROM candidates WHERE id = ?",
                            (disk_cid,)).fetchone()[0] if disk_cid else None
    if disk_key in keys:
        if disk_key not in specs or specs[disk_key] == conn.execute(
                "SELECT spec FROM candidates WHERE id = ?", (disk_cid,)).fetchone()[0]:
            return disk_cid, "confirmed"
        return C.ensure(conn, specs[disk_key], proposal=verdict["name"], key=disk_key,
                        lane=verdict["lane"] or run["lane"]), "receipt"
    try:
        aliases, _ = screen.gateway_routes()
    except Exception:  # noqa: BLE001
        aliases = set()
    typed = set(winners.typed().values())
    pool = []
    for key, spec in specs.items():
        name = spec.split(",", 1)[0]
        # A bare name is a gateway alias (serving.route), never a discovered repo.
        alias = name.lower() in aliases or (":" not in name and "/" not in name)
        if key not in keys or adopt.is_reference(spec) or spec in typed or alias:
            continue
        owner = conn.execute("SELECT proposal_id FROM candidates WHERE spec = ?",
                             (spec,)).fetchone()
        if owner is None or owner["proposal_id"] in (None, verdict["proposal_id"]):
            pool.append((key, spec))
    if len(pool) != 1:
        return disk_cid, "guessed"
    key, spec = pool[0]
    return C.ensure(conn, spec, proposal=verdict["name"], key=key,
                    lane=verdict["lane"] or run["lane"]), "receipt"


def _by_download(conn, label: str, lane: str) -> str:
    """The one spec, built from a downloaded repo, whose runner writes `label`. #429."""
    from harness import candidates as C, screen
    found = set()
    for r in conn.execute("SELECT DISTINCT repo FROM downloads "
                          "WHERE repo != ''").fetchall():
        try:
            spec = screen.candidate_for(lane, r["repo"], conn=conn)
        except Exception:  # noqa: BLE001
            spec = ""
        if spec and C.key_of(spec) == label:
            found.add(spec)
    return found.pop() if len(found) == 1 else ""


def _resolve_fakes(conn, fakes: dict, counts: dict) -> None:
    """Fold each spec-named proposal into the candidate it names. #407, #429."""
    from harness import candidates as C
    for pid, fake in fakes.items():
        counts["fakes"] += 1
        label = _legacy_spec(fake["name"])
        got = C.get(conn, label)
        if got is None and ":" in label:
            C.ensure(conn, label, lane=fake["lane"])
            got = C.get(conn, label)
        if got is None and fake["lane"]:
            spec = _by_download(conn, label, fake["lane"])
            if spec and C.ensure(conn, spec, key=label, lane=fake["lane"]):
                got = C.get(conn, spec)
        if got is None:
            counts["fakes_unresolved"] += 1
            continue
        target = got["proposal_id"] if got["proposal_id"] != pid else None
        newest = conn.execute(
            "SELECT state_verdict_id FROM proposals WHERE id = ?",
            (target,)).fetchone()[0] if target else None
        moved = conn.execute("SELECT id FROM verdicts WHERE proposal_id = ?",
                             (pid,)).fetchall()
        for v in moved:
            keep = target if newest is not None and v["id"] < newest else None
            conn.execute("UPDATE verdicts SET proposal_id = ?, candidate_id = ? "
                         "WHERE id = ?", (keep, got["id"], v["id"]))
        if target:
            counts["fakes_to_proposal"] += 1
        conn.execute("UPDATE candidates SET proposal_id = NULL "
                     "WHERE proposal_id = ?", (pid,))
        conn.execute("DELETE FROM proposals WHERE id = ?", (pid,))


def resolve_identity_leftovers(conn) -> dict:
    """Schema 37: variants get their proposal, spec-named proposals fold. #429."""
    from harness import candidates as C
    counts = {"fakes": 0, "fakes_to_proposal": 0, "fakes_unresolved": 0}
    _resolve_fakes(conn, {r["id"]: dict(r) for r in _adopted_by_name(conn)},
                   counts)
    counts["variants_linked"] = C.link_variants(conn)
    counts["downloads_linked"] = conn.execute(
        "UPDATE downloads SET proposal_id = (SELECT MIN(p.id) FROM proposals p "
        "WHERE lower(p.name) = lower(downloads.repo)) WHERE proposal_id IS NULL "
        "AND repo != '' AND EXISTS (SELECT 1 FROM proposals p "
        "WHERE lower(p.name) = lower(downloads.repo))").rowcount or 0
    counts["unlinked_results"] = conn.execute(
        "SELECT COUNT(*) AS n FROM results WHERE candidate_id IS NULL"
    ).fetchone()["n"]
    conn.commit()
    return counts


#: Evidence a v2 store already holds about where a name came from, strongest
#: first. Each rule only fills rows still empty, so a URL beats a kind: the
#: inspect tier wrote kind='repo' for a GitHub repo while from_feeds wrote the
#: same kind for a HuggingFace one, and the URL it recorded alongside says
#: which is which.
_BACKFILL = (
    ("url", "https://huggingface.co/%", HUGGINGFACE),
    ("url", "https://github.com/%", GITHUB),
    ("kind", "weights", HUGGINGFACE),
    ("kind", "tool", GITHUB),
    ("kind", "repo", HUGGINGFACE),
)


def _backfill_registry(conn) -> int:
    """Fill `registry` from what the store already recorded. Returns the count.

    A row with no evidence keeps the empty string. Guessing one for it would
    turn "nobody knows" into a wrong answer that nothing ever revisits, which
    is the failure this column exists to end.
    """
    filled = 0
    for field, value, registry in _BACKFILL:
        if field == "url":
            cur = conn.execute(
                "UPDATE proposals SET registry = ? WHERE registry = '' "
                "AND id IN (SELECT proposal_id FROM sightings WHERE url LIKE ?)",
                (registry, value))
        else:
            cur = conn.execute(
                "UPDATE proposals SET registry = ? WHERE registry = '' "
                "AND kind = ?", (registry, value))
        filled += cur.rowcount or 0
    conn.commit()
    return filled
