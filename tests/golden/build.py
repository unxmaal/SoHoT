"""Rebuild the golden stores (`uv run python tests/golden/build.py [version...]`); when a schema step lands, add (version, merge sha) to ERAS and seed what it introduced. #478."""
from __future__ import annotations

import ast
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from harness import machine  # noqa: E402

#: (schema, the commit that landed it): each golden is the DDL as of that commit.
ERAS = (
    (10, "e6ca30b"),
    (18, "a79b126"),
    (24, "c77e69e"),
    (29, "84f72ac"),
    (34, "9420086"),
    (38, "b522eb0"),
    (41, "77e9639"),
)

T0 = 1788600000.0
HOUR = 3600.0
GIB = 1024 ** 3


def at(hours: float) -> float:
    return T0 + hours * HOUR


def stamp(hours: float) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(at(hours)))


def git_show(sha: str, path: str) -> str | None:
    got = subprocess.run(["git", "show", f"{sha}:{path}"], cwd=REPO,
                         capture_output=True, text=True)
    return got.stdout if got.returncode == 0 else None


def old_store_module(sha: str) -> types.ModuleType:
    """harness/memory_store.py as of `sha`, executed in a throwaway module."""
    src = git_show(sha, "harness/memory_store.py")
    if src is None:
        raise SystemExit(f"{sha} is not in this clone; fetch the full history")
    mod = types.ModuleType(f"golden_memory_store_{sha}")
    sys.modules[mod.__name__] = mod
    try:
        exec(compile(src, f"{sha}:harness/memory_store.py", "exec"), mod.__dict__)
    finally:
        del sys.modules[mod.__name__]
    return mod


def side_ddl(sha: str) -> str:
    """Tables other modules created at `sha` (disk.py's disk_removals)."""
    src = git_show(sha, "harness/disk.py")
    if not src:
        return ""
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_DDL" for t in node.targets):
            return ast.literal_eval(node.value)
    return ""


def columns(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def has(conn, table: str) -> bool:
    return bool(columns(conn, table))


def ins(conn, table: str, **row) -> int | None:
    """Insert the keys this era's table has; None when the table does not exist."""
    cols = columns(conn, table)
    if not cols:
        return None
    row = {k: v for k, v in row.items() if k in cols}
    return conn.execute(
        f"INSERT INTO {table} ({', '.join(row)}) "
        f"VALUES ({', '.join('?' * len(row))})", tuple(row.values())).lastrowid


#: (key, hw_model, os, arch): one M2 Pro under two Pythons and a receipt
#: with no OS, the Studio, and one PC board under Linux and under Windows.
MACHINES = (
    ("m2", "Mac14,12", "macOS-26.0-arm64-arm-64bit", "arm64"),
    ("m2-macho", "Mac14,12", "macOS-26.0-arm64-arm-64bit-Mach-O", "arm64"),
    ("m2-no-os", "Mac14,12", "", "arm64"),
    ("studio", "Mac17,15", "macOS-27.0.1-arm64-arm-64bit", "arm64"),
    ("pc-linux", "B650M", "Linux-6.8.0-45-generic-x86_64-with-glibc2.39", "x86_64"),
    ("pc-windows", "B650M", "Windows-11-SP0", "AMD64"),
)
#: Folded into m2 by schema 33.
FOLDED = ("m2-macho", "m2-no-os")


def old_fingerprint(hw: str, os_: str, arch: str) -> str:
    return f"{hw}/{os_}/{arch}"


def seed_machines(conn, v: int) -> dict:
    ids: dict = {}
    if not has(conn, "machines"):
        return ids
    for n, (key, hw, os_, arch) in enumerate(MACHINES):
        if v >= 33 and key in FOLDED:
            continue
        fp = machine.fingerprint(hw, os_, arch) if v >= 33 \
            else old_fingerprint(hw, os_, arch)
        ids[key] = ins(conn, "machines", fingerprint=fp, hw_model=hw, os=os_,
                       arch=arch, memory_gb=32.0 if hw == "Mac14,12" else 64.0,
                       accelerator="metal 32GB" if hw.startswith("Mac")
                       else "cuda 12GB",
                       runtimes="llamacpp,mlx" if hw.startswith("Mac")
                       else "cuda,llamacpp,vllm",
                       ceiling_gb=23.0, first_seen=at(n), last_seen=at(400 + n),
                       versions=json.dumps({"mlx": "0.29.0"}) if hw.startswith("Mac")
                       else "{}")
    if v >= 33:
        for key in FOLDED:
            hw, os_, arch = next(m[1:] for m in MACHINES if m[0] == key)
            ins(conn, "machine_merges", from_id=90 + FOLDED.index(key),
                from_fingerprint=old_fingerprint(hw, os_, arch),
                into_id=ids["m2"], repointed=json.dumps({"runs": 1}),
                merged_at=at(300))
        ids.update({k: ids["m2"] for k in FOLDED})
    return ids


#: name, registry, lane, description, card facts (hf_task, library, attaches_to).
PROPOSALS = (
    ("org-a/coder-7b-GGUF", "huggingface", "code",
     "task text-generation; served by llamacpp; tagged gguf, code",
     ("text-generation", "gguf", "")),
    ("org-b/huge-70b", "huggingface", "code", "task text-generation",
     ("text-generation", "transformers", "")),
    ("org-c/old-repo", "github", "", "A training script for a vision model", ("", "", "")),
    ("org-d/lora-x", "huggingface", "image",
     "task text-to-image; adapter of org-z/base-xl", ("text-to-image", "diffusers", "lora")),
    ("org-e/vllm-only", "huggingface", "code", "task text-generation; served by vllm",
     ("text-generation", "vllm", "")),
    ("org-f/screen-broke", "huggingface", "image", "task text-to-image",
     ("text-to-image", "diffusers", "")),
    ("org-g/gguf-llama", "huggingface", "code", "task text-generation; tagged gguf",
     ("text-generation", "gguf", "")),
    ("org-h/tts-model", "huggingface", "tts", "task text-to-speech",
     ("text-to-speech", "mlx", "")),
    ("org-i/queued-only", "huggingface", "", "a small model", ("", "", "")),
    ("org-j/never-judged", "github", "", "", ("", "", "")),
    ("org-k/harness-broke", "huggingface", "code", "task text-generation",
     ("text-generation", "mlx", "")),
    ("org-l/svg-thing", "huggingface", "svg", "task text-generation; tagged svg",
     ("text-generation", "mlx", "")),
    ("org-m/image-gen", "huggingface", "image", "task text-to-image",
     ("text-to-image", "mflux", "")),
)

#: spec, receipt key, lane, proposal name or None.
CANDIDATES = (
    ("llamacpp:coder-7b-Q4_K_M", "coder-7b", "code", "org-a/coder-7b-GGUF"),
    ("local-mid", "local-mid", "code", None),
    ("mflux:org-m/image-gen", "image-gen", "image", "org-m/image-gen"),
    ("diffusers:org-f/screen-broke", "screen-broke", "image", "org-f/screen-broke"),
    ("mlx:org-h/tts-model", "tts-model", "tts", "org-h/tts-model"),
    ("kokoro", "kokoro", "tts", None),
    ("mlx:org-l/svg-thing", "svg-thing", "svg", "org-l/svg-thing"),
    ("local-large", "local-large", "svg", None),
)

#: name, runs-dir path, lane, tier, machine key, hours, specs, rows
#: (candidate, case, passed, artifact).
CODE = "def add(a, b):\n    return a + b\n"
RUNS = (
    ("20260910-120000-0001-code", "code", "screen", "m2", 120,
     {"coder-7b": "llamacpp:coder-7b-Q4_K_M", "local-mid": "local-mid"},
     [("coder-7b", "add", True, CODE), ("coder-7b", "sort", True, CODE),
      ("coder-7b", "parse", False, ""), ("local-mid", "add", True, CODE),
      ("local-mid", "sort", False, CODE), ("local-mid", "parse", False, None)]),
    ("20260912-090000-0002-image", "image", "screen", "m2-no-os", 150,
     {"image-gen": "mflux:org-m/image-gen",
      "screen-broke": "diffusers:org-f/screen-broke"},
     [("image-gen", "cat", True, "/RUNS/0002-image/image-gen-cat.png"),
      ("image-gen", "dog", True, "/RUNS/0002-image/image-gen-dog.png"),
      ("screen-broke", "cat", False, ""), ("screen-broke", "dog", False, "")]),
    ("20260920-100000-0003-tts", "tts", "measure", "studio", 330,
     {"tts-model": "mlx:org-h/tts-model", "kokoro": "kokoro"},
     [("tts-model", "hello#1", True, "/RUNS/0003-tts/tts-model-hello.wav"),
      ("tts-model", "hello#2", False, "/RUNS/0003-tts/tts-model-hello-2.wav"),
      ("kokoro", "hello#1", True, "/RUNS/0003-tts/kokoro-hello.wav"),
      ("kokoro", "hello#2", True, "/RUNS/0003-tts/kokoro-hello-2.wav")]),
)
SNAP = "/HF/hub/models--{}/snapshots/0a1b2c3d"


def snapshot(name: str) -> str:
    return SNAP.format(name.replace("/", "--"))


def history(v: int, fp: dict) -> list[dict]:
    """Every verdict, in id order, as this era's writers would have left it."""
    m2 = fp.get("m2", "Mac14,12/macOS-26.0-arm64-arm-64bit/arm64")
    fits = "fits: {} GiB of weights under the 23.0 GiB ceiling"
    out = [
        dict(p="org-a/coder-7b-GGUF", tier="inspect", outcome="queued",
             detail=fits.format(4.4), reason="candidate", size_bytes=int(4.4 * GIB), h=10),
        dict(p="org-a/coder-7b-GGUF", tier="judge", outcome="queued",
             detail="judged relevant", score=0.81, rubric="relevance",
             judge="local-mid", reason="candidate", h=11),
        dict(p="org-a/coder-7b-GGUF", tier="fetch", outcome="queued",
             detail="downloaded", run_path=snapshot("org-a/coder-7b-GGUF"),
             reason="candidate", h=12),
        dict(p="org-a/coder-7b-GGUF", tier="screen", outcome="screened",
             detail="passed 2/3", score=0.67, run_path="runs/" + RUNS[0][0],
             run=0, cand="llamacpp:coder-7b-Q4_K_M", reason="candidate", h=121),
        dict(p="org-a/coder-7b-GGUF", tier="adopt", outcome="measured",
             detail="code: adopted over local-mid at 0.67 vs 0.33",
             score=0.67, run_path="runs/" + RUNS[0][0], run=0,
             cand="llamacpp:coder-7b-Q4_K_M", reason="candidate", h=122),
        dict(p="org-b/huge-70b", tier="inspect", outcome="declined",
             detail="too-big: 39.5 GiB of weights over the 23.0 GiB ceiling",
             until="ceiling_gb:>39.5" if v >= 18 else "", reason="machine",
             size_bytes=int(39.5 * GIB), h=13),
        dict(p="org-c/old-repo", tier="inspect", outcome="declined",
             detail="dead: last commit 2.9 years ago", reason="upstream",
             upstream_idle_days=1059.0, stale_days=1059.0, h=14),
        dict(p="org-d/lora-x", tier="inspect", outcome="ignored",
             detail="attaches to a model: lora in its own card",
             attaches_to="lora", reason="candidate", h=15),
        dict(p="org-e/vllm-only", tier="inspect", outcome="queued",
             detail=fits.format(14.0), reason="candidate", h=16),
        dict(p="org-e/vllm-only", tier="fetch", outcome="declined",
             detail=(f"needs-vllm on {m2}: no vllm on this machine" if v < 33
                     else "needs-vllm: no vllm on this machine"),
             until="runtime:vllm" if v >= 12 else "", reason="machine", h=17),
        dict(p="org-g/gguf-llama", tier="inspect", outcome="declined",
             detail="needs-llamacpp", until="runtime:llamacpp" if v >= 12 else "",
             reason="machine", h=18),
        dict(p="org-h/tts-model", tier="inspect", outcome="queued",
             detail=fits.format(0.3), reason="candidate", h=19),
        dict(p="org-h/tts-model", tier="fetch", outcome="queued", detail="downloaded",
             run_path=snapshot("org-h/tts-model"), reason="candidate", h=20),
        dict(p="org-h/tts-model", tier="screen", outcome="screened",
             detail="passed 1/2", score=0.5, run_path="runs/" + RUNS[2][0], run=2,
             cand="mlx:org-h/tts-model", reason="candidate", h=331),
        dict(p="org-h/tts-model", tier="measure", outcome="declined",
             detail="lost to the incumbent: 0.50 vs 1.00", score=0.5,
             run_path="runs/" + RUNS[2][0], run=2, cand="mlx:org-h/tts-model",
             reason="candidate", h=332),
        dict(p="org-i/queued-only", tier="inspect", outcome="queued",
             detail=fits.format(2.0), reason="candidate", h=21),
        dict(p="org-l/svg-thing", tier="adopt", outcome="measured",
             detail="svg: preferred by hand over local-large",
             cand="mlx:org-l/svg-thing", reason="candidate", h=340),
        dict(p="org-m/image-gen", tier="screen", outcome="screened",
             detail="passed 2/2", score=1.0, run_path="runs/" + RUNS[1][0], run=1,
             cand="mflux:org-m/image-gen", reason="candidate", h=151),
    ]
    if v < 16:
        # Schema 16 retracts these: terminal on no evidence. #281.
        out += [dict(p="org-f/screen-broke", tier="screen", outcome="broken",
                     detail="it ran and passed nothing", h=152 + i) for i in (0, 1)]
    else:
        out.append(dict(p="org-f/screen-broke", tier="screen", outcome="broken",
                        detail="it ran and passed nothing: 0/2", score=0.0,
                        run_path="runs/" + RUNS[1][0], run=1,
                        cand="diffusers:org-f/screen-broke", reason="candidate",
                        h=152))
    out.append(dict(p="org-k/harness-broke", tier="screen", outcome="broken",
                    detail="the screen exited 1: generation thread died",
                    reason="harness", h=160))
    if v >= 22:
        out.append(dict(p="org-k/harness-broke", tier="inspect", outcome="queued",
                        detail="retracted: generation thread died is this harness",
                        reopen_kind="retraction", reason="reopened", h=161))
    for r in out:
        r.setdefault("machine", "m2" if r["h"] < 300 else "studio")
    return sorted(out, key=lambda r: r["h"])


def seed(conn, v: int, home: Path) -> dict:
    """The one history, placed where schema `v` kept each fact."""
    ids = seed_machines(conn, v)
    fps = {k: conn.execute("SELECT fingerprint FROM machines WHERE id = ?",
                           (i,)).fetchone()[0] for k, i in ids.items()}
    pid = {}
    for n, (name, reg, lane, desc, (task, lib, attaches)) in enumerate(PROPOSALS):
        # Before schema 34 the size cache, not the store, held this lane. #416.
        if name == "org-i/queued-only" and v >= 34:
            lane = "code"
        pid[name] = ins(
            conn, "proposals", name=name, kind="candidate", registry=reg,
            description=desc, lane=lane, first_seen=at(n), last_seen=at(200 + n),
            hf_task=task, library=lib, attaches_to=attaches,
            card_tags=json.dumps(["gguf"] if lib == "gguf" else []),
            lane_source="card" if task else "", card_read="card" if task else "")
        ins(conn, "sightings", proposal_id=pid[name],
            source="hf-trending" if reg == "huggingface" else "github-search",
            url=f"https://example.org/{name}", why="trending this week",
            relevance=2, seen_at=at(n),
            machine_id=ids.get("m2") if v >= 38 else None)
    if has(conn, "lineage"):
        ins(conn, "lineage", proposal_id=pid["org-d/lora-x"],
            parent="org-z/base-xl", kind="adapter")
    edge = dict(src=pid["org-a/coder-7b-GGUF"], dst=pid["org-h/tts-model"],
                relation="crowd")
    if v >= 34:
        ins(conn, "edges", **edge, note="", shared=3, crowd=12, score=0.25)
    else:
        ins(conn, "edges", **edge, note="3/12 at 0.25")
    ins(conn, "extractions", name="not-a-model", source="hf-trending",
        reason="not-a-repo", at=at(5))

    cid = {}
    if has(conn, "candidates"):
        for spec, key, lane, prop in CANDIDATES:
            cid[spec] = ins(conn, "candidates", proposal_id=pid.get(prop),
                            spec=spec, receipt_key=key, lane=lane, created_at=at(100))

    run_ids = seed_runs(conn, v, home, ids, cid)

    vids = []
    for r in history(v, fps):
        cols = dict(proposal_id=pid[r["p"]], outcome=r["outcome"], tier=r["tier"],
                    detail=r["detail"], run_path=r.get("run_path", ""),
                    score=r.get("score"), rubric=r.get("rubric", ""),
                    judge=r.get("judge", ""), decided_at=at(r["h"]),
                    size_bytes=r.get("size_bytes", 0), until=r.get("until", ""),
                    attaches_to=r.get("attaches_to", ""),
                    candidate_id=cid.get(r.get("cand")),
                    run_id=run_ids.get(r.get("run")),
                    reason=r.get("reason", ""), reopen_kind=r.get("reopen_kind", ""))
        if v >= 12:
            cols["machine_id"] = ids.get(r["machine"])
        if v >= 15:
            cols["upstream_idle_days"] = r.get("upstream_idle_days", 0.0)
        elif v >= 14:
            cols["stale_days"] = r.get("stale_days", 0.0)
        if v >= 31 and r["tier"] == "fetch":
            cols["run_path"] = ""
        if r.get("reopen_kind"):
            held = conn.execute("SELECT state_verdict_id FROM proposals WHERE "
                                "id = ?", (pid[r["p"]],)).fetchone() \
                if "state_verdict_id" in columns(conn, "proposals") else None
            cols["reopens"] = held[0] if held else None
        vid = ins(conn, "verdicts", **cols)
        vids.append((r, vid))
        if "state" in columns(conn, "proposals"):
            conn.execute("UPDATE proposals SET state = ?, state_verdict_id = ? "
                         "WHERE id = ?", (r["outcome"], vid, pid[r["p"]]))
    if "next_retest_at" in columns(conn, "proposals"):
        for r, vid in vids:
            if r["p"] == "org-h/tts-model" and r["tier"] == "measure":
                conn.execute("UPDATE proposals SET next_retest_at = ? WHERE id = ?",
                             (at(r["h"]) + 7 * 86400, pid[r["p"]]))
    if has(conn, "adoptions"):
        by = {(r["p"], r["tier"]): vid for r, vid in vids}
        ins(conn, "adoptions", lane="code", candidate_id=cid["llamacpp:coder-7b-Q4_K_M"],
            incumbent_id=cid["local-mid"], run_id=run_ids[0],
            verdict_id=by[("org-a/coder-7b-GGUF", "adopt")], machine_id=ids["m2"],
            how="measured", adopted_at=at(122))
        ins(conn, "adoptions", lane="svg", candidate_id=cid["mlx:org-l/svg-thing"],
            verdict_id=by[("org-l/svg-thing", "adopt")], machine_id=ids["studio"],
            how="by-hand", adopted_at=at(340))
    seed_votes(conn, v, home, ids)
    seed_downloads(conn, v, home, ids, pid, vids)
    seed_legacy(conn, v, home, ids)
    return pid


def seed_runs(conn, v: int, home: Path, ids: dict, cid: dict) -> dict:
    """Receipts on disk in every era; rows from schema 27; the split from 41."""
    run_ids = {}
    runs = home / "runs"
    for n, (name, lane, tier, mkey, hours, specs, rows) in enumerate(RUNS):
        hw, os_, arch = next(m[1:] for m in MACHINES if m[0] == mkey)
        env = {"hw_model": hw, "os": os_, "arch": arch}
        receipt = {"modality": lane, "tier": tier, "cases_digest": f"digest-{n}"}
        out = [{"candidate": c, "case_id": case, "passed": ok, "seconds": 2.5,
                "peak_kb": 1024 * 512, "detail": "" if ok else "failed: wrong answer",
                "metrics": {}, "warnings": [], "artifact": art}
               for c, case, ok, art in rows]
        d = runs / name
        d.mkdir(parents=True)
        (d / "results.json").write_text(json.dumps(
            {"generated": stamp(hours), "environment": env, "receipt": receipt,
             "specs": specs, "rows": out}, indent=1, sort_keys=True), encoding="utf-8")
        if not has(conn, "runs"):
            continue
        run_ids[n] = ins(conn, "runs", path=name, lane=lane, tier=tier,
                         machine_id=ids.get(mkey), generated_at=at(hours),
                         repeat_count=1, cases_digest=f"digest-{n}",
                         receipt=json.dumps(receipt), environment=json.dumps(env),
                         specs=json.dumps(specs), recorded_at=at(hours),
                         job_id=2 if (v >= 35 and n == 2) else None)
        media = lane in ("image", "tts")
        for seq, (c, case, ok, art) in enumerate(rows):
            base, _, rep = case.partition("#")
            ins(conn, "results", run_id=run_ids[n], seq=seq,
                candidate_id=cid.get(specs[c]), candidate=c, case_id=case,
                repeat_index=int(rep or 1), passed=int(ok), seconds=2.5,
                peak_kb=1024 * 512, detail="" if ok else "failed: wrong answer",
                metrics="{}", warnings="[]", artifact=art,
                output=None if media or not art else art,
                artifact_path=art if media and art else None,
                failure_class="" if ok else "content_failed")
    (runs / "rubric-20260915").mkdir(parents=True)
    (runs / "rubric-20260915" / "results.json").write_text(
        json.dumps({"rubric": "svg", "scores": {}}), encoding="utf-8")
    (runs / "20260916-000000-0004-empty").mkdir(parents=True)
    return run_ids


VOTES = (
    {"lane": "svg", "case": "icon-1", "left": "local-large", "right": "svg-thing",
     "winner": "svg-thing", "shown_first": "left"},
    {"lane": "svg", "case": "icon-1", "left": "local-large", "right": "svg-thing",
     "winner": "svg-thing", "shown_first": "left"},
    {"lane": "image", "case": "cat", "left": "image-gen", "right": "screen-broke",
     "winner": "image-gen", "shown_first": "right"},
)
FILE_MTIME = at(330)


def seed_votes(conn, v: int, home: Path, ids: dict) -> None:
    (home / "human-verdicts.json").write_text(json.dumps(list(VOTES), indent=1),
                                              encoding="utf-8")
    if not has(conn, "human_votes"):
        return
    for r in VOTES:
        lo, hi = sorted((r["left"], r["right"]))
        ins(conn, "human_votes", lane=r["lane"], run="", case_id=r["case"],
            left_candidate=lo, right_candidate=hi, winner=r["winner"],
            shown_first=r["shown_first"], voter="", machine_id=None, at=FILE_MTIME)
    ins(conn, "human_votes", lane="image", run=RUNS[1][0], case_id="dog",
        left_candidate="image-gen", right_candidate="screen-broke",
        winner="image-gen", shown_first="left", voter="judge-page",
        machine_id=ids.get("m2"), at=at(360))


GGUF_SOURCES = {"org-g/gguf-llama": "gguf-llama-Q4_K_M.gguf"}


def seed_downloads(conn, v, home, ids, pid, vids) -> None:
    (home / "gguf-sources.json").write_text(json.dumps(GGUF_SOURCES, indent=1),
                                            encoding="utf-8")
    removed = snapshot("org-f/screen-broke")
    if has(conn, "disk_removals"):
        ins(conn, "disk_removals", path=removed, repo="org-f/screen-broke",
            grp="rejected", bytes=3 * GIB, verdict_id=None, source="lh disk",
            removed_at=at(200))
    if not has(conn, "downloads"):
        return
    for name in ("org-a/coder-7b-GGUF", "org-h/tts-model"):
        ins(conn, "downloads", proposal_id=pid[name], repo=name, kind="hub",
            path=snapshot(name), origin="backfill", bytes=GIB, files=4, complete=1,
            requires="[]", started_at=at(12), finished_at=at(12),
            machine_id=ids["m2"])
    ins(conn, "downloads", proposal_id=pid["org-g/gguf-llama"], repo="org-g/gguf-llama",
        kind="gguf", path="/GGUF/gguf-llama-Q4_K_M.gguf", file="gguf-llama-Q4_K_M.gguf",
        origin="backfill", bytes=0, complete=0, started_at=at(250),
        finished_at=at(250), removed_at=at(250), removed_by="absent at backfill",
        machine_id=ids["m2"])
    ins(conn, "downloads", proposal_id=pid["org-f/screen-broke"],
        repo="org-f/screen-broke", kind="hub", path=removed, origin="backfill",
        bytes=3 * GIB, complete=0, removed_at=at(200), removed_by="lh disk",
        machine_id=ids["m2"])


MEMORY_LIMITS = {old_fingerprint(*MACHINES[0][1:]): [
    {"measured_at": "2026-09-20T10:00:00", "margin_gb": 6.5,
     "last_normal_gb": 25.5, "stopped": "floor"}]}
FETCHED = {"hf-trending": at(390), "github-search": at(391)}
HF_SIZES = {"org-i/queued-only": {"bytes": 2 * GIB, "lane": "code"},
            "org-j/never-judged": {"bytes": 0}}
JOBS = (
    {"id": "0001", "title": "soh discover", "kind": "command", "output": "",
     "priority": 0, "argv": ["soh", "discover"], "cwd": "/REPO", "state": "done",
     "added": "2026-09-19T09:00:00", "started": "2026-09-19T09:00:05",
     "finished": "2026-09-19T09:10:00", "rc": 0, "log": "/LOGS/0001.log"},
    {"id": "0002", "title": "tts measure", "kind": "command", "output": "",
     "priority": 5, "argv": ["uv", "run", "python", "-m", "evals.run"],
     "cwd": "/REPO", "state": "failed", "added": "2026-09-20T09:00:00",
     "started": "2026-09-20T09:00:05", "finished": "2026-09-20T10:00:00",
     "rc": 1, "log": "/LOGS/0002.log", "note": "one case failed"},
)


def seed_legacy(conn, v: int, home: Path, ids: dict) -> None:
    """The JSON files a home keeps after a migration imported them."""
    (home / "memory-limits.json").write_text(json.dumps(MEMORY_LIMITS, indent=1),
                                             encoding="utf-8")
    (home / "discovery-state.json").write_text(
        json.dumps({"fetched": FETCHED}, indent=1), encoding="utf-8")
    (home / "cache" / "github").mkdir(parents=True)
    (home / "cache" / "github" / "hf-sizes.json").write_text(
        json.dumps(HF_SIZES, indent=1), encoding="utf-8")
    (home / "queue" / "jobs").mkdir(parents=True)
    for j in JOBS:
        (home / "queue" / "jobs" / f"{j['id']}.json").write_text(
            json.dumps(j, indent=1), encoding="utf-8")
    if has(conn, "memory_limits"):
        for r in MEMORY_LIMITS[old_fingerprint(*MACHINES[0][1:])]:
            ins(conn, "memory_limits", machine_id=ids["m2"], measured_at=at(330),
                margin_gb=r["margin_gb"], last_normal_gb=r["last_normal_gb"],
                stopped=r["stopped"], report=json.dumps(r, sort_keys=True))
    if has(conn, "sources"):
        for name, when in FETCHED.items():
            ins(conn, "sources", name=name, kind="", url="", enabled=1,
                last_read_at=when, last_attempt_at=when, last_status="ok")
    if has(conn, "jobs") and v >= 35:
        for j in JOBS:
            ins(conn, "jobs", id=int(j["id"]), title=j["title"], kind=j["kind"],
                priority=j["priority"], argv=json.dumps(j["argv"]), cwd=j["cwd"],
                state=j["state"], created_at=at(330), rc=j["rc"], log=j["log"],
                note=j.get("note", ""), requested_by="migration",
                machine_id=ids["m2"])


def build(version: int, sha: str, out: Path) -> Path:
    """One golden store: out/v<N>/discovery.sql and out/v<N>/home/."""
    mod = old_store_module(sha)
    if mod.SCHEMA_VERSION != version:
        raise SystemExit(f"{sha} speaks schema {mod.SCHEMA_VERSION}, not {version}")
    dest = out / f"v{version}"
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        conn = sqlite3.connect(Path(tmp) / "discovery.db")
        conn.executescript(mod._DDL + side_ddl(sha))
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)",
                     (str(version),))
        seed(conn, version, home)
        conn.commit()
        sql = "\n".join(conn.iterdump()) + "\n"
        conn.close()
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        (dest / "discovery.sql").write_text(sql, encoding="utf-8")
        shutil.copytree(home, dest / "home")
    return dest


def load(golden: Path, into: Path) -> tuple[Path, Path]:
    """A working copy of one golden: (discovery.db, home)."""
    home = into / "home"
    shutil.copytree(golden / "home", home)
    os.utime(home / "human-verdicts.json", (FILE_MTIME, FILE_MTIME))
    db = home / "discovery.db"
    conn = sqlite3.connect(db)
    conn.executescript((golden / "discovery.sql").read_text(encoding="utf-8"))
    conn.close()
    return db, home


def main(argv: list[str]) -> int:
    want = {int(a) for a in argv} or {v for v, _ in ERAS}
    for version, sha in ERAS:
        if version in want:
            print(build(version, sha, HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
