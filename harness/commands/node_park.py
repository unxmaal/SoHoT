"""`soh node-park park|unpark NAME`: set one node's parked line in nodes.yaml (#2135)."""
from __future__ import annotations

from harness.commands.common import emit, err, note


def add_parser(sub) -> None:
    p = sub.add_parser("node-park", help="park or unpark one node in nodes.yaml: a parked node is kept but left out of "
                       "routing, fallbacks, probes and checks; the gateway reads the file when it loads")
    p.add_argument("action", choices=("park", "unpark"))
    p.add_argument("name", help="a node nodes.yaml names")
    p.set_defaults(func=cmd_node_park)


def cmd_node_park(a) -> int:
    from harness import node_park
    try:
        got = node_park.set_parked(a.name, a.action == "park")
    except ValueError as exc:
        return err(str(exc))
    note(f"node {got['node']} {'parked' if got['parked'] else 'unparked'} in {got['file']}" if got["changed"]
         else f"node {got['node']} was already {'parked' if got['parked'] else 'unparked'}")
    emit(**got)
    return 0
