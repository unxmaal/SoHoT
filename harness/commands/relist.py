"""`soh router relist`: restart the router once for what it lists with no file or does not list yet (#2018)."""
from __future__ import annotations

from harness import relist, router
from harness.commands.common import emit, err, note


def add_parser(sub) -> None:
    p = sub.add_parser("router", help="the llama-server router on this machine")
    verbs = p.add_subparsers(dest="router_verb", required=True)
    r = verbs.add_parser("relist", help="restart the router once for what it lists with no file or does not list yet")
    r.set_defaults(func=cmd_relist)


def cmd_relist(a) -> int:
    found = router.phantoms()
    if found is None:
        return err(f"router relist: the router at {router.url()} did not answer GET /models")
    why = relist.run(found, say=note)
    if why:
        return err(f"router relist: {why}")
    emit(True, phantoms=found)
    return 0
