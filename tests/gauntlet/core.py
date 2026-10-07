"""Binds this repo's defects to the gauntlet skill's classes, and finds the ones closed without a class (#492)."""

import ast
import json
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNAPSHOT_FILE = HERE / "skill_classes.json"
DEFECTS_FILE = HERE / "defects.json"
SKILL_FILES = ("SKILL.md", "general-corpus.md")
REPO_SLUG = "unxmaal/SoHoT"

_CLOSING = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#(\d+)")


def slug(heading):
    text = re.sub(r"^\d+\.\s*", "", heading.strip())
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _field(body, label):
    # The paragraph that opens with **Label:**, joined onto one line.
    lead = f"**{label}:**"
    for i, line in enumerate(body):
        if line.startswith(lead):
            para = [line[len(lead):]]
            for nxt in body[i + 1:]:
                if not nxt.strip():
                    break
                para.append(nxt)
            return " ".join(" ".join(para).split())
    return ""


def parse_skill(text, source):
    found, heading, body = [], None, []

    def close():
        if heading is None:
            return
        m = re.search(r"\*\*Tier:\*\*\D*?(\d)", "\n".join(body))
        b = re.search(r"\*\*Bitten:\*\*\D*?(\d+)", "\n".join(body))
        if m:
            found.append({"id": slug(heading), "heading": heading, "source": source, "tier": int(m.group(1)),
                          "bitten": int(b.group(1)) if b else None,
                          "trigger": _field(body, "Trigger"), "test_shape": _field(body, "Test shape")})

    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("# "):
            close()
            heading = line[3:].strip() if line.startswith("## ") else None
            body = []
        elif heading is not None:
            body.append(line)
    close()
    return found


def skill_dir():
    override = os.environ.get("GAUNTLET_SKILL_DIR")
    if override:
        return Path(override)
    return Path(os.path.expanduser("~")) / ".claude" / "skills" / "gauntlet"


def read_skill(directory):
    out = []
    for name in SKILL_FILES:
        out += parse_skill((Path(directory) / name).read_text(encoding="utf-8"), name)
    return out


def load_snapshot():
    return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))


def load_defects():
    rows = json.loads(DEFECTS_FILE.read_text(encoding="utf-8"))
    return {r["number"]: {"title": r["title"], "created": r["created"]} for r in rows}


def _issues(entry):
    return [i["issue"] for i in entry.get("instances", []) if isinstance(i, dict) and "issue" in i]


def bound(index, pending):
    out = set()
    for entry in list(index.values()) + list(pending.values()):
        out.update(_issues(entry))
    return out


def _scanner_exists(repo, ref):
    path, _, name = ref.partition("::")
    file = Path(repo) / path
    if not file.is_file() or not name:
        return False
    tree = ast.parse(file.read_text(encoding="utf-8"))
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name for n in tree.body)


def _instance_problems(cid, entry, defects):
    out = []
    instances = entry["instances"]
    if not instances:
        out.append(f"{cid}: no instance; a class is bound here only once it has bitten")
    for inst in instances:
        if not (isinstance(inst, dict) and len(inst) == 1 and set(inst) <= {"issue", "rule"}
                and all(isinstance(v, int) for v in inst.values())):
            out.append(f"{cid}: bad instance {inst!r}; use {{'issue': N}} or {{'rule': N}}")
        elif "issue" in inst and inst["issue"] not in defects:
            out.append(f"{cid}: #{inst['issue']} is not in the defects snapshot")
    return out


def _binding_field_problems(cid, entry):
    out = []
    for site, why in entry.get("waivers", {}).items():
        if not str(why).strip():
            out.append(f"{cid}: waiver {site} has no reason")
    if "review" in entry:
        try:
            re.compile(entry["review"])
        except (re.error, TypeError) as e:
            out.append(f"{cid}: review heuristic does not compile: {e}")
    return out


def _tier(cid, entry, tiers):
    return entry.get("tier", tiers.get(cid))


def problems(index, pending, unclassified, snapshot, defects, repo):
    out = []
    tiers = {c["id"]: c["tier"] for c in snapshot}
    for cid, entry in index.items():
        if cid not in tiers:
            out.append(f"{cid}: not in the skill snapshot; propose it as PENDING instead")
        if "tier" in entry and not str(entry.get("tier_reason", "")).strip():
            out.append(f"{cid}: tier rebound here with no tier_reason")
        missing = [f for f in ("instances", "scanners") if f not in entry]
        for f in missing:
            out.append(f"{cid}: missing {f}")
        if missing:
            continue
        out += _instance_problems(cid, entry, defects)
        out += _binding_field_problems(cid, entry)
        for ref in entry["scanners"]:
            if not _scanner_exists(repo, ref):
                out.append(f"{cid}: scanner {ref} does not exist")
    for cid, entry in pending.items():
        if cid in tiers:
            out.append(f"{cid}: the skill now defines it; move it from PENDING into INDEX")
        if "tier" not in entry:
            out.append(f"{cid}: missing tier")
        if "instances" not in entry:
            out.append(f"{cid}: missing instances")
            continue
        out += _instance_problems(cid, entry, defects)
    named = bound(index, pending)
    for n, why in unclassified.items():
        if n in named:
            out.append(f"#{n}: both classified and unclassified")
        if not str(why).strip():
            out.append(f"#{n}: unclassified with no reason")
        if n not in defects:
            out.append(f"#{n}: unclassified but not in the defects snapshot")
    for n in sorted(set(defects) - named - set(unclassified)):
        out.append(f"#{n}: a defect in the snapshot with no class and no reason")
    return out


def unscanned(index, snapshot):
    tiers = {c["id"]: c["tier"] for c in snapshot}
    return sorted(cid for cid, e in index.items() if _tier(cid, e, tiers) == 1 and not e.get("scanners"))


def bite_drift(index, snapshot):
    out = []
    for c in snapshot:
        if c.get("bitten") is None or c["id"] not in index:
            continue
        here = len(_issues(index[c["id"]]))
        if here != c["bitten"]:
            out.append((c["id"], c["bitten"], here))
    return out


def closing_refs(text):
    return {int(n) for n in _CLOSING.findall(text)}


def unattributed(labelled, index, pending, unclassified):
    known = bound(index, pending) | set(unclassified)
    return sorted(n for n in labelled if n not in known)


def unbound_closures(messages, defect_numbers, index, pending, unclassified):
    known = bound(index, pending) | set(unclassified)
    out = []
    for msg in messages:
        for n in sorted(closing_refs(msg)):
            if n in defect_numbers and n not in known:
                out.append((n, msg))
    return out


def stats(index, pending, snapshot, defects):
    tiers = {c["id"]: c["tier"] for c in snapshot}
    per_tier, instances, rules, first, after = {}, {}, {}, {}, {}
    entries = [(cid, e, _tier(cid, e, tiers)) for cid, e in index.items()]
    entries += [(cid, e, e.get("tier")) for cid, e in pending.items()]
    for cid, entry, tier in entries:
        per_tier[tier] = per_tier.get(tier, 0) + 1
        issues = _issues(entry)
        instances[cid] = len(issues)
        rules[cid] = sum(1 for i in entry.get("instances", []) if "rule" in i)
        dates = sorted(defects[n]["created"] for n in issues if n in defects)
        if dates:
            first[cid] = dates[0]
            after[cid] = sum(1 for d in dates if d > dates[0])
    total = sum(instances[c] for c in after)
    return {"classes_per_tier": per_tier, "instances": instances, "rules": rules, "first": first,
            "after_first": after, "kill_rate": (sum(after.values()) / total) if total else None}


def report(labelled, snapshot_numbers, closures, index, pending, unclassified, snapshot, defects):
    lines = []
    gaps = unattributed(labelled, index, pending, unclassified)
    lines.append(f"closed defects with no class: {len(gaps)}")
    lines += [f"  #{n} has no class and no reason" for n in gaps]
    stale = sorted(set(labelled) - set(snapshot_numbers))
    lines.append(f"closed defects not in the snapshot: {len(stale)}")
    lines += [f"  #{n} is not in the snapshot; run snapshot-defects" for n in stale]
    lines.append(f"closing references to a defect with no class: {len(closures)}")
    lines += [f"  #{n} closed by: {msg.strip().splitlines()[0][:80]}" for n, msg in closures]
    lines.append(f"unclassified, with a reason: {len(unclassified)}")
    s = stats(index, pending, snapshot, defects)
    lines.append("classes per tier: " + ", ".join(
        f"tier {t}: {n}" for t, n in sorted(s["classes_per_tier"].items(), key=lambda kv: (kv[0] is None, kv[0]))))
    lines += [f"tier 1 with no scanner yet: {cid}" for cid in unscanned(index, snapshot)]
    lines += [f"skill says bitten {b}, this repo has {h}: {cid}" for cid, b, h in bite_drift(index, snapshot)]
    lines.append(f"pending classes awaiting a skill entry: {len(pending)}")
    lines.append("instances per class (issues / rules / after the first):")
    for cid in sorted(s["instances"], key=lambda c: (-s["instances"][c], c)):
        lines.append(f"  {s['instances'][cid]:3d} {s['rules'][cid]:3d} {s['after_first'].get(cid, 0):3d}  {cid}"
                     + ("  (pending)" if cid in pending else ""))
    kr = s["kill_rate"]
    lines.append("kill rate: " + ("n/a" if kr is None else
                 f"{kr:.2f} of attributed defects arrived after their class's first instance"))
    return "\n".join(lines)


def _gh(argv):
    proc = subprocess.run(["gh", *argv], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(proc.stdout)


def gh_defects():
    rows = _gh(["issue", "list", "--repo", REPO_SLUG, "--state", "closed", "--label", "defect",
                "--limit", "1000", "--json", "number,title,createdAt"])
    return {r["number"]: {"title": r["title"], "created": r["createdAt"]} for r in rows}


def gh_merged_pr_bodies():
    rows = _gh(["pr", "list", "--repo", REPO_SLUG, "--state", "merged", "--limit", "1000",
                "--json", "number,title,body"])
    return [f"{r['title']}\n{r['body']}" for r in rows]


def git_messages(repo, ref="origin/main"):
    # None when this clone lacks `ref`: a CI checkout is one commit with no origin/main.
    have = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=repo,
                          capture_output=True, text=True, encoding="utf-8")
    if have.returncode != 0:
        return None
    proc = subprocess.run(["git", "log", ref, "--format=%B%x00"], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", check=True)
    return [m for m in proc.stdout.split("\x00") if m.strip()]
