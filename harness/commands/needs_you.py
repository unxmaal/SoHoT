"""`soh needs-you`: what stops work, as the status page's band lists it; --alert sends what began or cleared (#2134)."""
from __future__ import annotations

from harness.commands.common import emit, note


def add_parser(sub) -> None:
    p = sub.add_parser("needs-you", help="every condition that stops work, as the status page's Needs-you band lists "
                       "it; --alert sends the alerts for those that began or cleared since the last pass")
    p.add_argument("--alert", action="store_true", help="alert each condition that began or cleared (monit runs this)")
    p.set_defaults(func=cmd_needs_you)


def cmd_needs_you(a) -> int:
    from harness import needs_you, status_page
    r = status_page.gather(light=True)
    if a.alert:
        needs_you.reconcile_monit(r.get("monitor"))
    conds = needs_you.conditions(r)
    note(*(f"{c['title']}: {c['why']}" if c["why"] else c["title"] for c in conds) or ["Nothing is stopped."])
    sent = needs_you.sync(r) if a.alert else None
    emit(conditions=conds, alerts=sent)
    return 0
