"""The per-item buttons on the status page: each listed job, unit, node, lane and the discovery loop, offered only what the gathered status lists (#2135)."""
from __future__ import annotations

from harness import owner_actions as oa


def offered(r: dict) -> dict[str, set[str]]:
    """Each action's choices as the gathered status offers them now; the same lists press() checks."""
    return {a.name: {v for v, _ in a.offers(r)} for a in oa.ACTIONS if a.offers}


def _forms(got: dict, tok: str, wanted: list[tuple[str, str]]) -> str:
    return "".join(oa.button(action, arg, tok, bare=True) for action, arg in wanted if arg in got.get(action, ()))


def _job_row(got: dict, tok: str, jid: str, text: str, actions: tuple[str, ...]) -> str:
    from harness import status_view as sv
    first = next((a for a in sorted(got.get("job_first", ())) if a.startswith(jid + ":")), "")
    buttons = _forms(got, tok, [(a, first if a == "job_first" else jid) for a in actions])
    return f"<div class='jr' data-job='{sv.esc(jid)}'><span class='jt'>{sv.esc(text)}</span><span class='fa'>{buttons}</span></div>"


def jobs(r: dict, tok: str) -> str:
    """The Queue tile's rows: running, waiting and failed or stuck jobs, each with the buttons that fit it."""
    got = offered(r)
    q, out, seen = r.get("queue") or {}, [], set()
    for j in q.get("running") or []:
        seen.add(str(j["id"]))
        out.append(_job_row(got, tok, str(j["id"]), f"running job {j['id']} {j.get('kind')}: {j.get('title')}", ("job_cancel",)))
    for j in q.get("waiting") or []:
        seen.add(str(j["id"]))
        held = " (held by benchmarks)" if j.get("held") else ""
        out.append(_job_row(got, tok, str(j["id"]), f"waiting job {j['id']} p{j.get('priority')}: {j.get('title')}{held}",
                            ("job_cancel", "job_let", "job_first")))
    for j in ((r.get("stops") or {}).get("jobs") or {}).get("rows") or []:
        if str(j["id"]) in seen:
            continue
        acts = ("job_retry",) if j["state"] == "failed" else ("job_cancel",)
        out.append(_job_row(got, tok, str(j["id"]), f"{j['state']} job {j['id']} {j.get('kind')}: {j.get('title')}", acts))
    return f"<div class='rows' data-rows='jobs'>{''.join(out)}</div>" if out else ""


def discovery(r: dict, tok: str) -> str:
    """The Discovery tile's row: start while no sweep step waits, else stop for each waiting step."""
    from harness import status_view as sv
    got = offered(r)
    queued = [str(x) for x in got.get("discovery_off", ())]
    wanted = [("discovery_on", "")] if not queued else [("discovery_off", x) for x in sorted(queued)]
    buttons = "".join(oa.button(a, arg, tok, bare=True) for a, arg in wanted)
    return (f"<div class='rows' data-rows='discovery'><div class='jr'><span class='jt'>"
            f"{sv.esc('continuous discovery: ' + ('on, a sweep step waits' if queued else 'no sweep step waits'))}</span>"
            f"<span class='fa'>{buttons}</span></div></div>")


def store(r: dict, tok: str) -> str:
    """The Store tile's row: the dump button while no daily dump was made today."""
    from harness import status_view as sv
    if not oa.backup_due(r):
        return ""
    return (f"<div class='rows' data-rows='store'><div class='jr'><span class='jt'>{sv.esc('no dump made today')}</span>"
            f"<span class='fa'>{oa.button('pg_backup', '', tok, bare=True)}</span></div></div>")


#: The Features switches an owner flips: row name -> (action when on, action when not).
SWITCHES = {"deploys": ("deploy_pause", "deploy_resume"), "review": ("review_off", "review_on")}


def feature(r: dict, tok: str):
    """A function (kind, name) -> the buttons for that Features row, '' for a row nothing acts on."""
    got = offered(r)
    by_kind = {"unit": ("unit_restart",), "node": ("node_park", "node_unpark"), "lane": ("lane_reverify",)}

    def acts(kind: str, name: str) -> str:
        if kind == "switch":
            on, off = SWITCHES.get(name, ("", ""))
            row = next((x for x in (r.get("features") or {}).get("rows") or [] if x.get("kind") == kind and x.get("name") == name), {})
            act = on if row.get("state") == "on" else off if row.get("state") in ("off", "paused") else ""
            return oa.button(act, "", tok, bare=True) if act else ""
        return _forms(got, tok, [(a, name) for a in by_kind.get(kind, ())])
    return acts


def closed_lanes(r: dict, tok: str):
    """A function lane -> the open-anyway or close-again button for that Closed lanes row. #2164."""
    got = offered(r)
    return lambda lane: _forms(got, tok, [("lane_open", lane), ("lane_close", lane)])
