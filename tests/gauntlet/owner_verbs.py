"""Owner-facing soh verbs: each is a status-page Action or a listed exemption (#2136).

Owner-facing means a leaf verb the owner runs to change what the machine does next: start, stop, hold,
reorder or cancel queued work, deploy, restart a unit, route or park a node, adopt or decline a model,
switch a store or volume. Reads, reports, one-shot generation, measurement, labelling and agent tooling
are not owner-facing and are grouped under NOT_OWNER with the reason.
"""
import argparse

NO_BUTTON = "no button yet, see #2138"
READ = "read-only report; changes nothing"
GENERATE = "one-shot generation for the caller; changes no standing state"
MEASURE = "measurement or replay over stored rows; no standing state changes"
LABEL = "labelling by hand needs a screen, not a tap"
DEV = "developer or agent tooling run in a checkout"
UNIT = "run by its own launchd unit, not by hand"

# A verb is a leaf path ("deploy now"); every owner verb with no Action is here, with why.
OWNER_EXEMPT = {
    "jobs add": "takes an arbitrary command; not one tap",
    "deploy pause": NO_BUTTON,
    "deploy resume": NO_BUTTON,
    "deploy poll": NO_BUTTON,
    "deploy nodes": NO_BUTTON,
    "deploy repair": NO_BUTTON,
    "deploy run": "the deploy job's own step; only the queue runs it",
    "deploy migrate": "the deploy job's own step and a store migration: too dangerous for one tap",
    "gate hold": "folded into hold gpu, which is the gate_hold button",
    "gate release": "folded into hold release gpu, which is the gate_release button",
    "adopt": NO_BUTTON,
    "decline": NO_BUTTON,
    "propose": "takes free text naming a technique; not one tap",
    "review on": NO_BUTTON,
    "review off": NO_BUTTON,
    "router relist": NO_BUTTON,
    "monitor install": "installs the monit config; a deploy step, not one tap",
    "monitor alert": "sent by monit itself, not by hand",
    "volume stop": "stops everything reading the models volume: too dangerous for one tap",
    "volume start": "starts everything reading the models volume after a disk swap: not one tap",
    "store switch": "switches the live store backend: too dangerous for one tap",
    "store migrate-to-postgres": "migrates the live store: too dangerous for one tap",
    "store export-to-sqlite": "writes the live store out; a terminal job",
    "store pg-up": "starts the store's Postgres; a terminal job",
    "store pg-down": "stops the store's Postgres: too dangerous for one tap",
    "store pg-roles": "rewrites database roles: too dangerous for one tap",
    "store pg-backup": NO_BUTTON,
    "store pg-restore": "overwrites the live store from a backup: too dangerous for one tap",
    "quarantine": NO_BUTTON,
    "gguf-aux": "--apply moves model files; a terminal job",
    "gateway key": "prints the gateway secret, which must never reach a page",
    "headless run": "starts a claude -p session; a terminal job",
}

# A verb path covers itself and every verb beneath it.
NOT_OWNER = {
    **dict.fromkeys(["image", "video", "svg", "web", "prompt", "code", "extract", "decide", "say", "voices",
                     "hear", "spans", "ask", "digest", "local", "delegated", "tool-route", "unverified"],
                    GENERATE),
    **dict.fromkeys(["report", "repo-report", "repo-route", "baseline", "throughput", "usage", "api-spend",
                     "claude-news", "context", "ledger", "inventory", "morning", "sweep-check", "runtimes",
                     "funnel", "families", "availability", "knobs", "measure-order", "lane-feed", "otel",
                     "needs-you", "worktrees", "disk", "memory", "benchmarks", "audit", "discover-why",
                     "specs", "votes", "gate status", "hold status", "jobs list", "deploy status",
                     "monitor render", "monitor status", "volume status", "store pg-status",
                     "store pg-check", "store dry-run", "interactive", "ci-times", "burndown", "fetch",
                     "kb-filter", "review stats", "blame", "gauntlet", "yield-stop", "climb"], READ),
    **dict.fromkeys(["label-score", "label-select", "rubric", "vision", "craft", "judge", "repo-screen",
                     "staging", "degenerate", "floors", "coherence", "load-log", "cases", "weedout-replay",
                     "reuse-replay", "residency-sim", "route-trial", "canary", "verify", "sensitivity",
                     "headless env", "headless exec", "atomic", "chaos"], MEASURE),
    **dict.fromkeys(["scaffold", "fix", "review run"], DEV),
    "watchdog": UNIT,
}


def verb_paths(parser: argparse.ArgumentParser) -> set[tuple[str, ...]]:
    """Every verb the parser accepts: subcommands, and positionals that choose one (hold benchmarks)."""
    out: set[tuple[str, ...]] = set()

    def walk(p, path):
        for a in p._actions:
            if isinstance(a, argparse._SubParsersAction):
                for name, sub in a.choices.items():
                    out.add(path + (name,))
                    walk(sub, path + (name,))
            elif path and a.choices and not a.option_strings:
                out.update(path + (str(c),) for c in a.choices if str(c))

    walk(parser, ())
    return out


def leaves(paths: set[tuple[str, ...]]) -> set[tuple[str, ...]]:
    return {p for p in paths if not any(q[:len(p)] == p and q != p for q in paths)}


def bound(argvs, paths: set[tuple[str, ...]]) -> set[tuple[str, ...]]:
    """The deepest verb each Action's argv spells, reading words until one is no verb."""
    out = set()
    for argv in argvs:
        cur: tuple[str, ...] = ()
        for w in argv:
            if cur + (w,) not in paths:
                break
            cur += (w,)
        if cur:
            out.add(cur)
    return out


def _words(verb: str) -> tuple[str, ...]:
    return tuple(verb.split())


def check(paths, bound_verbs, owner_exempt, not_owner) -> list[str]:
    """Every leaf is bound, exempt or not owner-facing, once; every named verb exists."""
    leaf = leaves(paths)
    found = []
    for v in sorted(bound_verbs - leaf):
        found.append(f"an Action spells '{' '.join(v)}', which is not a leaf verb of the parser")
    for name, table in (("owner exemption", owner_exempt), ("not-owner entry", not_owner)):
        for verb, why in table.items():
            if _words(verb) not in paths:
                found.append(f"{name} '{verb}' names a verb the parser no longer has")
            if not why or "\n" in why:
                found.append(f"{name} '{verb}' needs a one-line reason")
    covered_by_not_owner = {v for v in leaf if any(v[:len(_words(k))] == _words(k) for k in not_owner)}
    exempt = {_words(v) for v in owner_exempt}
    for v in sorted(bound_verbs & leaf):
        if v in exempt or v in covered_by_not_owner:
            found.append(f"'{' '.join(v)}' has an Action and is also exempted")
    for v in sorted(exempt & covered_by_not_owner):
        found.append(f"'{' '.join(v)}' is both an owner exemption and not owner-facing")
    for v in sorted(leaf - bound_verbs - exempt - covered_by_not_owner):
        found.append(f"'{' '.join(v)}' has no status-page Action, no exemption and is not listed as not owner-facing")
    return found
