"""The environment a manual `launchd.sh install` records, and whether the installed units still carry it (#1518)."""
from __future__ import annotations

import os
import plistlib
import re
import sys
from pathlib import Path

from harness import deploy_switch, paths

REPO = Path(__file__).resolve().parent.parent
PREFIX = "com.unxmaal.localharness"


def path(home=None) -> Path:
    return Path(home or paths.home()) / deploy_switch.INSTALL_ENV


def read(p=None) -> dict:
    return deploy_switch.read_install_env(path() if p is None else p)


def problem(p=None) -> str:
    """Why a reinstall would refuse this record, or ''."""
    p = path() if p is None else Path(p)
    if not p.is_file():
        return f"no recorded install environment at {p}: run scripts/launchd.sh install once from the owner's shell"
    hf = read(p).get("HF_HOME", "")
    if not hf:
        return f"{p} records no HF_HOME: run scripts/launchd.sh install again"
    try:
        os.listdir(hf)
    except OSError as exc:
        return f"the weights location {p} records (HF_HOME={hf}) cannot be read: {exc.strerror or exc}"
    return ""


def services(script=None) -> list[str]:
    """The units scripts/launchd.sh installs, read from its SERVICES line."""
    text = Path(script or REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    got = re.search(r'^SERVICES="([^"]+)"', text, re.M)
    return got.group(1).split() if got else []


def units(record: dict, agents: Path, names=None) -> list[tuple[bool, str]]:
    """(passed, line) per installed unit: its rendered HF_HOME against the recorded one."""
    want = record.get("HF_HOME", "")
    out = []
    for name in names if names is not None else services():
        plist = Path(agents) / f"{PREFIX}.{name}.plist"
        if not plist.is_file():
            continue
        try:
            env = plistlib.loads(plist.read_bytes()).get("EnvironmentVariables") or {}
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            out.append((False, f"unit {name}: {plist} does not parse ({exc})"))
            continue
        got = str(env.get("HF_HOME", ""))
        if got == want:
            out.append((True, f"unit {name} carries the recorded HF_HOME"))
        else:
            out.append((False, f"unit {name} has HF_HOME={got or 'nothing'}, not the recorded {want}: "
                               f"run scripts/launchd.sh install"))
    return out


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m harness.install_env")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="exit 1 when reinstall would refuse the record")
    u = sub.add_parser("units", help="each installed unit's HF_HOME against the record")
    u.add_argument("--agents", default="", help="the LaunchAgents directory (default ~/Library/LaunchAgents)")
    args = p.parse_args(argv)
    why = problem()
    if args.cmd == "check" or why:
        print(f"FAIL  {why}" if why else f"PASS  {path()} names a readable weights location")
        return 1 if why else 0
    from harness import volume
    rows = units(read(), Path(args.agents) if args.agents else volume.agents_dir())
    for ok, line in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {line}")
    if not rows:
        print("SKIP  no installed units to compare with the record")
    return 0 if all(ok for ok, _ in rows) else 1


if __name__ == "__main__":
    from harness import env
    env.guard()
    sys.exit(main())
