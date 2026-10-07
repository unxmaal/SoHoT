"""python -m tests.gauntlet {audit,snapshot-skill,snapshot-defects} (#492)."""

import argparse
import json
import sys
from pathlib import Path

from tests.gauntlet import classes, core

REPO = core.HERE.parent.parent


def cmd_audit(a):
    snapshot, defects = core.load_snapshot(), core.load_defects()
    if a.offline:
        labelled, messages = sorted(defects), core.git_messages(REPO, a.ref)
    else:
        labelled = sorted(core.gh_defects())
        messages = core.git_messages(REPO, a.ref) + core.gh_merged_pr_bodies()
    closures = core.unbound_closures(messages, set(labelled) | set(defects), classes.INDEX,
                                     classes.PENDING, classes.UNCLASSIFIED)
    print(core.report(labelled, set(defects), closures, classes.INDEX, classes.PENDING,
                      classes.UNCLASSIFIED, snapshot, defects))
    gaps = core.unattributed(labelled, classes.INDEX, classes.PENDING, classes.UNCLASSIFIED)
    return 1 if gaps or closures else 0


def cmd_snapshot_skill(a):
    found = core.read_skill(Path(a.skill_dir) if a.skill_dir else core.skill_dir())
    core.SNAPSHOT_FILE.write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8")
    print(f"{len(found)} classes -> {core.SNAPSHOT_FILE.relative_to(REPO)}")
    return 0


def cmd_snapshot_defects(a):
    rows = [{"number": n, **v} for n, v in sorted(core.gh_defects().items())]
    core.DEFECTS_FILE.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    print(f"{len(rows)} defects -> {core.DEFECTS_FILE.relative_to(REPO)}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tests.gauntlet")
    sub = p.add_subparsers(dest="cmd", required=True)
    au = sub.add_parser("audit", help="closed defects with no class, and the registry's numbers")
    au.add_argument("--offline", action="store_true", help="use the committed snapshot, no gh")
    au.add_argument("--ref", default="origin/main", help="history whose commit messages are read")
    au.set_defaults(fn=cmd_audit)
    sk = sub.add_parser("snapshot-skill", help="regenerate skill_classes.json from the gauntlet skill")
    sk.add_argument("--skill-dir", help="default: $GAUNTLET_SKILL_DIR, else the user's skill directory")
    sk.set_defaults(fn=cmd_snapshot_skill)
    sd = sub.add_parser("snapshot-defects", help="regenerate defects.json from closed `defect` issues")
    sd.set_defaults(fn=cmd_snapshot_defects)
    a = p.parse_args(argv)
    return a.fn(a)


# TODO(#492): wire as `soh gauntlet audit` once harness/cli.py is split (#484).
if __name__ == "__main__":
    sys.exit(main())
