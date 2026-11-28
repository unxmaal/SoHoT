"""`soh owner-picks`: the owner's blind picks on a perceptual lane's holdout win (#2183)."""
from __future__ import annotations

from harness.commands.common import emit, err


def add_parser(sub) -> None:
    p = sub.add_parser("owner-picks", help="the owner's blind A/B picks a perceptual lane's holdout win waits on")
    sp = p.add_subparsers(dest="picks_cmd", required=True)
    sp.add_parser("list", help="each waiting item and how many pairs are left").set_defaults(func=cmd_list)
    one = sp.add_parser("pick", help="record a choice on one pair; the last pair adopts or declines the challenger")
    one.add_argument("item", type=int)
    one.add_argument("pair", type=int, help="the pair's number from 0")
    one.add_argument("choice", help="left, right or none")
    one.set_defaults(func=cmd_pick)


def cmd_list(a) -> int:
    from harness import memory_store as ms
    from harness import owner_picks
    conn = ms.connect()
    try:
        items = owner_picks.view(conn)
    finally:
        conn.close()
    for i in items:
        print(f"item {i['id']}: {i['lane']}, {i['open']} of {len(i['pairs'])} pairs left")
    if not items:
        print("no item waits for picks")
    emit(items=items)
    return 0


def cmd_pick(a) -> int:
    from harness import memory_store as ms
    from harness import owner_picks
    conn = ms.connect()
    try:
        try:
            _, said = owner_picks.pick(conn, a.item, a.pair, a.choice)
        except ValueError as exc:
            return err(str(exc))
    finally:
        conn.close()
    print(said)
    emit(said=said)
    return 0
