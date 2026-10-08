"""llama-server's router keeps the last model it loaded; give back what discovery loaded. #444."""
from __future__ import annotations

import contextlib
import json
import os
import urllib.request

from harness.serving import LLAMACPP_PREFIX, LLAMACPP_URL

#: Router statuses that hold memory.
RESIDENT = {"loaded", "loading", "sleeping"}
TIMEOUT = 5.0


def url() -> str:
    """The eval router, on LLAMACPP_PORT when set (scripts/serve-eval.sh)."""
    port = (os.environ.get("LLAMACPP_PORT") or "").strip()
    return f"{LLAMACPP_URL.rsplit(':', 1)[0]}:{port}" if port.isdigit() else LLAMACPP_URL


def _get(path: str) -> dict:
    with urllib.request.urlopen(url() + path, timeout=TIMEOUT) as r:
        return json.loads(r.read() or b"{}")


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(url() + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read() or b"{}")


def statuses(get=None) -> dict | None:
    """Router model id -> status value, None when the router cannot be asked."""
    try:
        data = (get or _get)("/models")
    except Exception:  # noqa: BLE001
        return None
    out = {}
    for m in data.get("data") or []:
        status = m.get("status")
        value = status.get("value") if isinstance(status, dict) else status
        if m.get("id"):
            out[str(m["id"])] = str(value)
    return out


def resident(get=None) -> list[str]:
    """Stems the router holds in memory, [] when it cannot be asked."""
    return [k for k, v in (statuses(get) or {}).items() if v in RESIDENT]


class Watch:
    """One eval candidate's router model across a run: each time it lost the model. #649."""

    def __init__(self, model: str, get=None) -> None:
        self.model = model
        self.get = get
        self.swaps: list[dict] = []
        self._held = False

    def look(self, case: str, at: str) -> None:
        """Record an eviction when the model was held and now is not; unknown is not one."""
        s = statuses(self.get)
        if s is None:
            return
        status = s.get(self.model, "absent")
        if status in ("loaded", "sleeping"):
            self._held = True
            return
        if self._held:
            self.swaps.append({"case": case, "at": at, "status": status,
                               "resident": sorted(k for k, v in s.items()
                                                  if v in RESIDENT and k != self.model)})
            self._held = False


def _upstream(spec: str, gateway: str = "") -> tuple:
    from harness import delegate, serving
    return delegate.upstream(serving.route(spec, gateway))


def model_for(spec: str, gateway: str = "", route=None) -> str:
    """The router model an eval candidate runs on, through a gateway alias too; "" otherwise."""
    try:
        base, model = (route or _upstream)(spec, gateway)
    except Exception:  # noqa: BLE001
        return ""
    from harness import serving
    return model if model and base in (serving.LLAMACPP_URL, url()) else ""


def stem_of(spec: str) -> str:
    return spec[len(LLAMACPP_PREFIX):] if (spec or "").startswith(LLAMACPP_PREFIX) else ""


def protected(conn=None, config=None) -> set[str]:
    """Stems a lane default, an adopted winner or a gateway alias serves. Raises if unreadable."""
    from harness import adopt, gateway, screen
    out = set()
    for entry in gateway.load(config).get("model_list") or []:
        model = gateway.strip_provider(
            str((entry.get("litellm_params") or {}).get("model", "")))
        if model:
            out.add(model)
    specs = [(lane, s) for lane, s in adopt.lane_defaults(conn).items()]
    close = conn is None
    if conn is None:
        from harness import memory_store as ms
        conn = ms.connect()
    try:
        specs += [(lane, s) for lane, ss in adopt.everywhere(conn).items() for s in ss]
        for lane, spec in specs:
            got = stem_of(spec) or stem_of(screen.candidate_for(lane, spec, conn=conn))
            if got:
                out.add(got)
    finally:
        if close:
            conn.close()
    return out


@contextlib.contextmanager
def _no_run_in_flight():
    """True while this process holds the eval lock nobody else had. #444."""
    from harness import exclusive
    if os.environ.get(exclusive.HELD_ENV) == "1":
        yield True
        return
    fd = os.open(exclusive.lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if not exclusive._take(fd):
            yield False
            return
        try:
            yield True
        finally:
            exclusive._release(fd)
    finally:
        os.close(fd)


def release(stems, why: str, *, get=None, post=None, keep=None, say=print) -> list[str]:
    """Unload each resident stem nothing protects, while no run is in flight."""
    wanted = [s for s in dict.fromkeys(stems) if s]
    if not wanted:
        return []
    held = resident(get)
    wanted = [s for s in wanted if s in held]
    if not wanted:
        return []
    try:
        keepers = protected() if keep is None else set(keep)
    except Exception as exc:  # noqa: BLE001
        say(f"  router: kept {', '.join(wanted)}: the lane defaults could not be read ({exc})")
        return []
    gone = []
    with _no_run_in_flight() as free:
        for stem in wanted:
            if stem in keepers:
                continue
            if not free:
                say(f"  router: kept {stem}: a run is in flight")
                continue
            try:
                (post or _post)("/models/unload", {"model": stem})
            except Exception as exc:  # noqa: BLE001
                say(f"  router: could not unload {stem}: {exc}")
                continue
            say(f"  router: unloaded {stem} ({why})")
            gone.append(stem)
    return gone


def release_spec(spec: str, why: str, **kw) -> list[str]:
    """release() for one candidate spec, if llama-server serves it."""
    return release([stem_of(spec)], why, **kw)


def settle(why: str, **kw) -> list[str]:
    """Leave only protected models resident."""
    return release(resident(kw.get("get")), why, **kw)
