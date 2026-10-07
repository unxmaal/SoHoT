"""python -m tests.gauntlet {audit,review,snapshot-skill,snapshot-defects} (#492)."""

import argparse
import json
import sys
from pathlib import Path

from tests.gauntlet import classes, core, review

REPO = core.HERE.parent.parent


def cmd_audit(a):
    snapshot, defects = core.load_snapshot(), core.load_defects()
    history = core.git_messages(REPO, a.ref)
    if a.offline:
        labelled, messages = sorted(defects), history or []
    else:
        labelled = sorted(core.gh_defects())
        messages = (history or []) + core.gh_merged_pr_bodies()
    closures = core.unbound_closures(messages, set(labelled) | set(defects), classes.INDEX,
                                     classes.PENDING, classes.UNCLASSIFIED)
    print(core.report(labelled, set(defects), closures, classes.INDEX, classes.PENDING,
                      classes.UNCLASSIFIED, snapshot, defects))
    if history is None:
        print(f"commit messages not read: {a.ref} is not in this clone")
    gaps = core.unattributed(labelled, classes.INDEX, classes.PENDING, classes.UNCLASSIFIED)
    return 1 if gaps or closures else 0


def cmd_review(a):
    fired = review.fire(review.changed(REPO, a.range), classes.INDEX, core.load_snapshot())
    print(review.render(fired))
    return 0


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
    rv = sub.add_parser("review", help="the review questions a diff raises, for classes no detector finds")
    rv.add_argument("range", nargs="?", default=review.DEFAULT_RANGE, help="a git range (default: %(default)s)")
    rv.set_defaults(fn=cmd_review)
    sk = sub.add_parser("snapshot-skill", help="regenerate skill_classes.json from the gauntlet skill")
    sk.add_argument("--skill-dir", help="default: $GAUNTLET_SKILL_DIR, else the user's skill directory")
    sk.set_defaults(fn=cmd_snapshot_skill)
    sd = sub.add_parser("snapshot-defects", help="regenerate defects.json from closed `defect` issues")
    sd.set_defaults(fn=cmd_snapshot_defects)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
