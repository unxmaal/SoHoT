"""Read-path A/B on recorded CI logs: tokens Claude reads raw against a checked digest, and the digest's failing-test recall. #1690."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import subprocess
from pathlib import Path

SET = Path(__file__).with_name("digest_ab")
MANIFEST = "manifest.json"
#: What Claude types to get either arm: a Read of the raw file, or one digest command.
READ_CALL = "Read {path}"
DIGEST_CALL = "soh digest {path}"
_PROGRESS = re.compile(r"^[.FEsxX]+\s*\[\s*\d+%\]$")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def progress_failures(text: str) -> int:
    """F and E marks on pytest -q progress lines: a count of failing tests that does not read the failure headers."""
    from harness import ask
    return sum(ln.count("F") + ln.count("E") for ln in ask.plain(text).splitlines() if _PROGRESS.match(ln.strip()))


def headers(text: str) -> int:
    """Failure headers across every job of the log, repeats kept, the count progress_failures should match."""
    from harness import ask, digest
    return sum(1 for ln in ask.plain(text).splitlines()
               if (m := digest._HEAD.match(ln.rstrip())) and not m.group(1).startswith(("Captured", "warnings summary")))


def gold(text: str) -> dict:
    from harness import digest
    items = digest.must(text)
    return {"tests": sorted(i.key for i in items if i.kind == "test"),
            "exits": sorted(i.key for i in items if i.kind == "exit")}


def gh_log(run: int) -> bytes:
    return subprocess.run(["gh", "run", "view", str(run), "--log-failed"], capture_output=True, check=True,
                          timeout=300).stdout


def build(runs, set_dir: Path = SET, fetch=gh_log, max_bytes: int | None = None) -> list[dict]:
    """Record each run's failed-job log under set_dir (gzip) with its gold; refuse a log whose failure headers and
    progress marks disagree, so the gold rests on two readings of the log."""
    from harness import ask
    cap = max_bytes or ask.MAX_BYTES
    set_dir = Path(set_dir)
    (set_dir / "logs").mkdir(parents=True, exist_ok=True)
    entries, refused = [], []
    for run in runs:
        data = fetch(int(run))
        text = data.decode("utf-8", "replace")
        if not data or len(data) > cap:
            refused.append({"run": run, "why": f"{len(data)} bytes, outside 1..{cap}"})
            continue
        g = gold(text)
        marks, heads = progress_failures(text), headers(text)
        if g["tests"] and marks != heads:
            refused.append({"run": run, "why": f"{heads} failure headers but {marks} progress marks"})
            continue
        name = f"{run}.log.gz"
        (set_dir / "logs" / name).write_bytes(gzip.compress(data, mtime=0))
        entries.append({"id": str(run), "run": int(run), "file": f"logs/{name}", "bytes": len(data),
                        "sha256": _sha(data), **g})
    (set_dir / MANIFEST).write_text(json.dumps({"entries": entries, "refused": refused}, indent=1) + "\n",
                                    encoding="utf-8")
    return entries


def materialize(out: Path, set_dir: Path = SET) -> list[dict]:
    """The set's logs written to out/logs as plain files, each checked against the manifest's sha256."""
    manifest = json.loads((Path(set_dir) / MANIFEST).read_text(encoding="utf-8"))
    (out / "logs").mkdir(parents=True, exist_ok=True)
    rows = []
    for e in manifest["entries"]:
        data = gzip.decompress((Path(set_dir) / e["file"]).read_bytes())
        if _sha(data) != e["sha256"]:
            raise ValueError(f"{e['file']} does not match its recorded sha256; the set is fixed, rebuild it whole")
        path = out / "logs" / f"{e['id']}.log"
        path.write_bytes(data)
        rows.append({**e, "path": str(path)})
    return rows


def _found(text: str, keys: list[str], kind: str) -> int:
    from harness import digest
    items = [digest.Item(kind, k, k) for k in keys]
    return len(items) - len(digest.missing(text, items))


def score(entry: dict, got: dict) -> dict:
    from harness import digest
    path = entry["path"]
    local = (got.get("prompt_tokens") or 0) + (got.get("completion_tokens") or 0)
    row = {"id": entry["id"], "bytes": entry["bytes"], "raw_tokens": got["raw_tokens"],
           "digest_tokens": got["digest_tokens"], "local_tokens": local, "calls": got.get("calls") or 0,
           "seconds": got.get("seconds") or 0.0, "model": got.get("model") or "", "unmodelled": got.get("unmodelled", ""),
           "read_call": digest.tokens(READ_CALL.format(path=path)),
           "digest_call": digest.tokens(DIGEST_CALL.format(path=path)),
           "tests": len(entry["tests"]), "exits": len(entry["exits"]), "control": got["check"]["control"],
           "added": got["check"]["added"]}
    for arm, text in (("model", got.get("model_text") or ""), ("shipped", got["answer"]), ("checked", got["text"])):
        row[f"tests_{arm}"] = _found(text, entry["tests"], "test")
        row[f"exits_{arm}"] = _found(text, entry["exits"], "exit")
    return row


def report(rows: list[dict], lane: str) -> dict:
    """Pooled totals: tokens per arm, recall per arm with a Wilson bound, and local:cloud under the #1688 rule."""
    from harness import intervals, ledger, purpose
    raw = sum(r["raw_tokens"] for r in rows)
    dig = sum(r["digest_tokens"] for r in rows)
    raw_arm = ledger.local_vs_cloud([], {"input": raw, "output": sum(r["read_call"] for r in rows)})
    dig_arm = ledger.local_vs_cloud([(purpose.WORK, lane, r["local_tokens"], 0) for r in rows],
                                    {"input": dig, "output": sum(r["digest_call"] for r in rows)})
    out = {"logs": len(rows), "with_tests": sum(1 for r in rows if r["tests"]), "raw_tokens": raw, "digest_tokens": dig,
           "fold": round(raw / dig, 1) if dig else None, "saved_tokens": raw_arm["cloud"] - dig_arm["cloud"],
           "raw_arm": raw_arm, "digest_arm": dig_arm,
           "ratio": dig_arm["local"] / dig_arm["cloud"] if dig_arm["cloud"] else None,
           "control": sum(1 for r in rows if r["control"]), "unmodelled": sum(1 for r in rows if r["unmodelled"]),
           "seconds": round(sum(r["seconds"] for r in rows), 1)}
    for what in ("tests", "exits"):
        n = sum(r[what] for r in rows)
        out[what] = n
        for arm in ("model", "shipped", "checked"):
            k = sum(r[f"{what}_{arm}"] for r in rows)
            out[f"{what}_{arm}"] = {"found": k, "of": n, "recall": round(k / n, 4) if n else None,
                                    "lower": intervals.wilson(k, n)[0]}
    return out


def lines(rep: dict) -> list[str]:
    from harness import ledger

    def rec(key: str) -> str:
        r = rep[key]
        return f"{r['found']}/{r['of']}" + (f" ({r['recall']:.0%}, Wilson lower {r['lower']:.2f})" if r["of"] else "")
    d = rep["digest_arm"]
    return [
        f"{rep['logs']} recorded CI logs, {rep['with_tests']} with failing tests ({rep['tests']} tests, {rep['exits']} exit lines)",
        f"tokens Claude reads: raw {rep['raw_tokens']:,}, digest {rep['digest_tokens']:,} "
        f"({rep['fold']}x fewer; {rep['saved_tokens']:,} cloud tokens saved)",
        f"failing tests kept: model alone {rec('tests_model')}; model + scan {rec('tests_shipped')}; "
        f"checked {rec('tests_checked')}",
        f"exit lines kept: model alone {rec('exits_model')}; model + scan {rec('exits_shipped')}; checked {rec('exits_checked')}",
        f"control caught a planted omission in {rep['control']}/{rep['logs']}; {rep['unmodelled']} log(s) had no model answer",
        f"local:cloud on the digest arm (#1688 rule): {d['local']:,} local / {d['cloud']:,} cloud = "
        f"{ledger._as_ratio(rep['ratio'])}, target {ledger._as_ratio(ledger.TARGET_RATIO)}; "
        f"the raw arm is 0 local / {rep['raw_arm']['cloud']:,} cloud",
    ]


def run(out: Path, *, model: bool = True, lane: str = "extract", complete=None, set_dir: Path = SET,
        progress=None) -> dict:
    """Digest every recorded log (no delegation rows: the caller runs in an eval home) and score it."""
    from harness import ask, digest
    out = Path(out)
    entries = materialize(out, set_dir)
    rows = []
    with open(out / "results.jsonl", "w", encoding="utf-8") as fh:
        for e in entries:
            got = digest.run([e["path"]], lane=lane, roots=[ask.Root(out / "logs")], delegated=False,
                             complete=complete, model=model)
            row = score(e, got)
            fh.write(json.dumps(row) + "\n")
            rows.append(row)
            if progress:
                progress(row)
    rep = report(rows, lane)
    rep["lines"] = lines(rep)
    (out / "report.json").write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    return rep


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="rebuild the recorded set from failed CI runs (gh run view --log-failed)")
    ap.add_argument("runs", nargs="+", type=int)
    ap.add_argument("--set", default=str(SET))
    a = ap.parse_args()
    got = build(a.runs, Path(a.set))
    print(f"{len(got)} logs recorded in {a.set}")
