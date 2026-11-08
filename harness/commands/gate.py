"""`soh gate status`: the contention gate GPU jobs and deploys wait for; the owner's hold on them is `soh hold gpu`. #1509."""
from __future__ import annotations

from harness.commands.common import emit, err, note


def cmd_gate(a) -> int:
    from harness import contention, hold
    from harness import memory_store as ms
    if a.action in ("hold", "release"):
        return err(f"the gate's hold is one scope of soh hold now: soh hold {hold.GPU} \"<who: why>\", "
                   f"{hold.RELEASE} {hold.GPU}")
    conn = ms.connect()
    try:
        v = contention.verdict(conn)
    finally:
        conn.close()
    note(f"contention gate {'open' if v['open'] else 'closed'}: {v['why']}")
    note(f"  memory pressure level {v['pressure_level']}; {v['served']} client request(s) in the last "
         f"{v['idle_s']:.0f} s (contention_idle){': ' + str(v['by_alias']) if v['by_alias'] else ''}")
    if v["hold"]:
        note(f"  {hold.line(v['hold'])}")
    emit(**v)
    return 0
