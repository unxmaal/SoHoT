"""The review questions a diff raises: classes no detector can find, whose cheap heuristic fires on added lines (#492 D)."""

import re
import subprocess

DEFAULT_RANGE = "origin/main...HEAD"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_SHOWN = 5
# Production code, unless a class names its own paths; the agent lane's case repos are inputs, not code.
CODE_PATHS = r"^(?:harness/|scripts/|evals/(?!cases/))"


def added_lines(diff):
    out, rel, line = {}, None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            rel = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            continue
        if raw.startswith("--- ") or raw.startswith("diff --git "):
            continue
        m = _HUNK.match(raw)
        if m:
            line = int(m.group(1))
            continue
        if rel is None:
            continue
        if raw.startswith("+"):
            out.setdefault(rel, []).append((line, raw[1:]))
            line += 1
        elif raw.startswith(" "):
            line += 1
    return out


def changed(repo, rng=DEFAULT_RANGE):
    proc = subprocess.run(["git", "diff", "--unified=0", "--no-color", "--no-ext-diff", rng], cwd=repo,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    return added_lines(proc.stdout)


def review_only(cid, entry, snap):
    tier = entry.get("tier", snap.get("tier"))
    return tier == 3 or (tier == 2 and not entry.get("detector"))


def fire(changed_lines, index, snapshot):
    snap = {c["id"]: c for c in snapshot}
    out = []
    for cid, entry in index.items():
        if not entry.get("review") or not review_only(cid, entry, snap.get(cid, {})):
            continue
        rx, paths = re.compile(entry["review"]), re.compile(entry.get("review_paths", CODE_PATHS))
        where = [f"{rel}:{n}" for rel, lines in sorted(changed_lines.items()) if paths.search(rel)
                 for n, text in lines if not text.lstrip().startswith("#") and rx.search(text)]
        if where:
            c = snap.get(cid, {})
            out.append({"id": cid, "heading": c.get("heading", cid), "tier": entry.get("tier", c.get("tier")),
                        "trigger": c.get("trigger", ""), "test_shape": c.get("test_shape", ""), "where": where})
    return out


def render(fired):
    if not fired:
        return "no review questions: no review-only class's trigger fired on the added lines"
    lines = [f"{len(fired)} review question(s) for the added lines; answer each, or say why it does not apply:"]
    for f in fired:
        shown = ", ".join(f["where"][:_SHOWN])
        more = f" and {len(f['where']) - _SHOWN} more" if len(f["where"]) > _SHOWN else ""
        lines += ["", f"{f['heading']} (tier {f['tier']})", f"  ask: {f['trigger']}",
                  f"  test: {f['test_shape']}", f"  where: {shown}{more}"]
    return "\n".join(lines)
