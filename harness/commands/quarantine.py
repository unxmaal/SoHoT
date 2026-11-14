"""`soh quarantine`: The quarantine dirs beside the GGUF dir: their sizes, and exact-copy duplicates that may go (#1921)."""
from __future__ import annotations

from harness.commands.common import emit, err, note


def add_parser(sub) -> None:
    p = sub.add_parser("quarantine", help="list the quarantine dirs beside the GGUF dir with their sizes; --dedupe "
                       "hashes same-size files and names each exact copy of a file that stays. #1921")
    p.add_argument("--dedupe", action="store_true", help="sha256 every same-size file and print each (kept, "
                   "duplicate) pair; deletes nothing without --apply")
    p.add_argument("--apply", action="store_true", help="with --dedupe, delete the duplicates it printed")
    p.set_defaults(func=cmd_quarantine)


def _rows(rows) -> None:
    from harness import disk
    for r in rows:
        note(f"  {disk.gib(r['bytes']):>7} GiB  {r['files']:>3} file(s)  {r['dir']}")


def cmd_quarantine(a) -> int:
    from harness import disk, quarantine
    if a.apply and not a.dedupe:
        return err("--apply deletes only what --dedupe finds; pass both")
    before = quarantine.sizes()
    _rows(before)
    note(quarantine.line(before))
    if not a.dedupe:
        emit(dirs=before)
        return 0
    pairs, refused = quarantine.plan()
    for p in pairs:
        note(f"same sha256 {p.sha256}  {p.drop.size} bytes\n  keep {p.keep.path}\n  drop {p.drop.path}")
    for path, why in refused:
        note(f"refused {path}: {why}")
    size = sum(p.drop.size for p in pairs)
    if not a.apply:
        note(f"{len(pairs)} exact duplicate(s), {disk.gib(size)} GiB ({size} bytes); "
             "dry run, nothing deleted (--apply deletes them)")
        emit(dirs=before, pairs=[_pair(p) for p in pairs], refused=[[str(p), w] for p, w in refused], bytes=size)
        return 0
    done = quarantine.drop(pairs)
    for r in done:
        if "error" in r:
            note(f"  not deleted: {r['drop']}: {r['error']}")
    freed = sum(r["bytes"] for r in done if "error" not in r)
    after = quarantine.sizes()
    _rows(after)
    note(f"deleted {sum('error' not in r for r in done)} of {len(done)}, freed {disk.gib(freed)} GiB "
         f"({freed} bytes); quarantine {disk.gib(sum(r['bytes'] for r in before))} -> "
         f"{disk.gib(sum(r['bytes'] for r in after))} GiB")
    ok = all("error" not in r for r in done)
    emit(ok, dirs=after, before=before, deleted=done, refused=[[str(p), w] for p, w in refused], bytes=freed)
    return 0 if ok else 1


def _pair(p) -> dict:
    return {"keep": str(p.keep.path), "drop": str(p.drop.path), "bytes": p.drop.size, "sha256": p.sha256}
