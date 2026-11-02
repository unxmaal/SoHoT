"""`soh monitor render|install|status|alert`: machine monitoring through monit (#1485)."""
from __future__ import annotations

from harness.commands.common import emit, err, note


def cmd_monitor(a) -> int:
    from harness import monitor
    if a.action == "render":
        try:
            text = monitor.render(monitor.spec_here())
        except ValueError as exc:
            return err(str(exc))
        if a.json:
            emit(config=text)
        else:
            print(text)
        return 0
    if a.action == "install":
        try:
            got = monitor.install()
        except (monitor.InstallError, ValueError) as exc:
            return err(str(exc))
        s = got["spec"]
        note(f"wrote {got['rc']} and {got['plist']}; monit loaded under launchd")
        note(f"watching {s['data']}" + (f", {s['models']}" if s["models"] else "")
             + ", memory pressure" + "".join(f", {n} :{p}" for n, p in s["services"]))
        note(f"alerts post to {monitor.WEBHOOK}" if got["webhook"] else
             f"no {monitor.WEBHOOK} in {monitor.env_path()}: alerts go to the desktop and the morning brief only")
        emit(**got)
        return 0
    if a.action == "alert":
        if not a.kind:
            return err(f"soh monitor alert needs a kind: {', '.join(monitor.KINDS)}")
        try:
            got = monitor.alert(a.kind)
        except ValueError as exc:
            return err(str(exc))
        note(f"{got['message']} [desktop: {got['desktop']}; webhook: {got['webhook']}]")
        if got.get("du"):
            note(got["du"])
        emit(**got)
        return 0
    got = monitor.status()
    if a.problems and not a.json:
        for p in got["problems"]:
            print(p)
        return 0
    note(f"monit {'installed' if got['installed'] else 'NOT installed'}; config {got['rc']} "
         + {True: "current", False: "STALE", None: "absent"}[got["current"]]
         + f"; {'running' if got['running'] else 'NOT running'}")
    for ln in got["summary"]:
        note(f"  {ln}")
    for p in got["problems"]:
        note(f"warn: {p}")
    emit(**got)
    return 0
