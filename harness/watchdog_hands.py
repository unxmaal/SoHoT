"""The fixed set of acts the watchdog takes: note, notify, file, pause, stop, reap, unload, restart. #814, #1909."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from typing import TYPE_CHECKING

from harness import audio_models, watchdog_observe

if TYPE_CHECKING:
    from harness.watchdog import Finding, Subject


def fingerprint(f: Finding) -> str:
    """Stable across wakes and pids: the criterion, the kind, and what was running."""
    s = f.subject
    what = json.dumps(sorted((s.progress or {}).get("specs") or {}), sort_keys=True) if s.progress else \
        re.sub(r"\d+", "N", s.command or s.key)
    return hashlib.sha256(f"{f.criterion}|{s.kind}|{what}".encode()).hexdigest()[:16]


def desktop(title: str, message: str, subtitle: str = "", run=subprocess.run, platform: str | None = None) -> str:
    """One macOS desktop notification through osascript; the outcome string. #818, #867."""
    from harness import watchdog as wd
    platform = platform or sys.platform
    if platform != "darwin":
        return wd.Said(f"notify unavailable: no desktop notifier on {platform} (macOS osascript only); "
                    "the row and the log line are the notice", wd.UNAVAILABLE)
    message = message[:200]
    # argv, not string interpolation, so a command line in the subject cannot break the AppleScript.
    script = ["osascript", "-e", "on run argv", "-e",
              "display notification (item 2 of argv) with title (item 1 of argv) subtitle (item 3 of argv)",
              "-e", "end run", title, message, subtitle[:120]]
    try:
        got = run(script, capture_output=True, text=True, timeout=wd.NOTIFY_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return wd.Said(f"notify failed: {exc}", wd.FAILED)
    if got.returncode != 0:
        return wd.Said(f"notify failed: osascript rc {got.returncode}: {(got.stderr or '').strip()[:200]}", wd.FAILED)
    return wd.Said(f"{wd.NOTIFIED}: {message}", wd.ACTED, notified=True)


def notice(title: str, message: str, subtitle: str = "", run=None, platform: str | None = None) -> str:
    """desktop() from the live home only, monitor.alert's gate; a scratch or test home's notice is not shown. #1794."""
    from harness import monitor, paths
    from harness import watchdog as wd
    if not monitor.live_home():
        return wd.Said(f"notify not sent: {paths.home()} is not the live home {paths.DEFAULT_HOME}", wd.UNAVAILABLE)
    return desktop(title, message, subtitle, run=run or subprocess.run, platform=platform)


#: Acts on what the machine-wide ps scan found (pgids, run dirs, the router, launchd units, GitHub); live home only. #1963.
MACHINE_ACTS = frozenset({"file", "pause", "stop", "reap", "unload", "restart"})


class Hands:
    """The fixed action set. Each returns an outcome string for the store row."""

    def __init__(self, reader: ProgressFiles | None = None, run=subprocess.run, environ=None, say=print,
                 platform: str | None = None):
        self.reader = reader or watchdog_observe.ProgressFiles()
        self.run = run
        self.environ = os.environ if environ is None else environ
        self.say = say
        self.platform = sys.platform if platform is None else platform

    def note(self, f: Finding) -> str:
        from harness import watchdog as wd
        return wd.Said("noted")

    def notify(self, f: Finding) -> str:
        from harness import watchdog as wd
        return notice(wd.NOTIFY_TITLE, f"{f.criterion}: {f.subject.key}", wd.BY_ID[f.criterion].what,
                      run=self.run, platform=self.platform)

    def file(self, f: Finding) -> str:
        from harness import watchdog as wd
        if self.environ.get(wd.FILE_ENV, "") != "1":
            return wd.Said(f"not filed: {wd.FILE_ENV} is not 1", wd.REFUSED)
        from harness import paths, privacy
        fp = fingerprint(f)
        title = f"watchdog: {f.criterion} on {f.subject.kind} ({wd.BY_ID[f.criterion].what})"
        body = (f"The watchdog (#814) judged `{f.criterion}` on {f.subject.key}.\n\n"
                f"Identified as: {f.subject.why}\n\nCommand: `{f.subject.command}`\n\n"
                f"Evidence:\n```json\n{json.dumps(f.evidence, indent=2, default=str)}\n```\n\n"
                f"{wd.FINGERPRINT} {fp}\n")
        found = privacy.check_post(f"{title}\n{body}")
        if found:
            return wd.Said(f"not filed: privacy: the issue would hold {', '.join(sorted({x.name for x in found}))}",
                        wd.REFUSED)
        try:
            seen = self.run(["gh", "issue", "list", "--state", "open", "--search", f"{fp} in:body",
                             "--json", "number", "--limit", "1"], capture_output=True, text=True,
                            timeout=wd.GH_TIMEOUT_S, cwd=paths.REPO)
            if seen.returncode != 0:
                return wd.Said(f"not filed: gh issue list failed: {seen.stderr.strip()[:200]}", wd.FAILED)
            hits = json.loads(seen.stdout or "[]")
            if hits:
                return f"already filed: #{hits[0]['number']}"
            made = self.run(["gh", "issue", "create", "--title", title, "--body", body], capture_output=True,
                            text=True, timeout=wd.GH_TIMEOUT_S, cwd=paths.REPO)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return wd.Said(f"not filed: {exc}", wd.FAILED)
        if made.returncode != 0:
            return wd.Said(f"not filed: gh issue create failed: {made.stderr.strip()[:200]}", wd.FAILED)
        return f"filed: {made.stdout.strip()}"

    def pause(self, f: Finding) -> str:
        from harness import watchdog as wd
        runs = f.subject.runs()
        if not runs:
            return wd.Said("pause unavailable: no progress file to pause through", wd.UNAVAILABLE)
        got = [wd.said(self.reader.pause(r, f.criterion)) for r in runs]
        return wd.Said("; ".join(got), wd.ACTED if any(g.result == wd.ACTED for g in got) else got[0].result)

    def _group(self, s: Subject) -> str:
        from harness import watchdog as wd
        from harness import job_procs
        if s.pgid is None:
            return wd.Said(f"refused: {s.key} has no process group made only of SoHoT processes", wd.REFUSED)
        return wd.Said(f"group {s.pgid}: {job_procs.stop_group(s.pgid, grace=wd.STOP_GRACE_S)}")

    def stop(self, f: Finding) -> str:
        if f.subject.pgid is not None:
            for r in f.subject.runs():
                self.reader.mark_stop(r, f.criterion)
        return self._group(f.subject)

    def reap(self, f: Finding) -> str:
        from harness import watchdog as wd
        if not f.subject.orphan:
            return wd.Said(f"refused: {f.subject.key} is not an orphan", wd.REFUSED)
        return self._group(f.subject)

    def unload(self, f: Finding) -> str:
        from harness import watchdog as wd
        from harness import router
        if f.criterion == "memory_warn":
            return self._unload_idle(f.evidence.get("idle") or [])
        if f.criterion == "memory_sustained":
            # A lane's own model goes too: the memory is what keeps the machine up, not its adoption. #1482.
            return self._unload_idle(f.evidence.get("spare") or [], keep=set(),
                                     why=f"watchdog: memory at warn for {f.evidence.get('samples')} wakes, "
                                         "loaded with no request in flight")
        if f.criterion == "idle_unload":
            # A lane's own model is given back too: the limit is what keeps it, not its adoption. #1157.
            return self._unload_idle([f.evidence], keep=set(),
                                     why=f"watchdog: no request for {f.evidence['idle_s']}s, "
                                         f"past {f.evidence['limit_s']:.0f}s")
        stem = f.subject.detail.get("stem", "")
        gone = router.release([stem], "watchdog: resident with nothing running", say=self.say)
        return wd.Said(f"unloaded {stem}") if gone else wd.Said(f"kept {stem}: protected, gone, or a run is in flight",
                                                          wd.REFUSED)

    def _unload_idle(self, idle: list, keep=None,
                     why: str = "watchdog: memory at warn, resident with no running eval using it") -> str:
        """Give back each idle model a memory_warn or idle_unload finding named. #1082, #1157."""
        from harness import watchdog as wd
        from harness import mlx_server, router
        if not idle:
            return wd.Said("nothing idle to unload: every resident model is in use or served", wd.UNAVAILABLE)
        out = []
        for m in idle:
            if m.get("server") == "mlx":
                gone = mlx_server.release(m["model"], why, keep=keep, say=self.say)
            else:
                gone = bool(router.release([m["model"]], why, keep=keep, say=self.say, proven_idle=True))
            out.append(f"{'unloaded' if gone else 'kept'} {m['server']} {m['model']}")
        return wd.Said("; ".join(out), wd.ACTED if any(o.startswith("unloaded") for o in out) else wd.REFUSED)

    def restart(self, f: Finding) -> str:
        from harness import watchdog as wd
        from harness import paths
        service = f.subject.detail.get("service", "")
        if service in ("mlx", "interactive"):
            return self._kickstart(service)
        if service not in ("gateway", audio_models.SERVICE):
            return wd.Said(f"refused: {service or f.subject.kind} is not a service the watchdog restarts", wd.REFUSED)
        try:
            got = self.run(["/bin/bash", str(paths.REPO / "scripts" / "launchd.sh"), "restart", service],
                           capture_output=True, text=True, timeout=wd.RESTART_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return wd.Said(f"restart of {service} still waiting on the GPU lock after {wd.RESTART_TIMEOUT_S:.0f}s", wd.FAILED)
        except OSError as exc:
            return wd.Said(f"restart of {service} failed: {exc}", wd.FAILED)
        return wd.Said(f"restarted {service}") if got.returncode == 0 else \
            wd.Said(f"restart of {service} failed rc {got.returncode}: {got.stderr.strip()[:200]}", wd.FAILED)

    def _kickstart(self, service: str) -> str:
        """kickstart -k without the GPU lock: a server that cannot generate has no work in flight to protect."""
        from harness import watchdog as wd
        if self.platform != "darwin":
            return wd.Said(f"refused: restarting {service} needs launchd (macOS); this is {self.platform}", wd.REFUSED)
        try:
            got = self.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{wd.LABEL}.{service}"],
                           capture_output=True, text=True, timeout=wd.RESTART_TIMEOUT_S)
        except (AttributeError, OSError, subprocess.SubprocessError) as exc:
            return wd.Said(f"restart of {service} failed: {exc}", wd.FAILED)
        return wd.Said(f"restarted {service}") if got.returncode == 0 else \
            wd.Said(f"restart of {service} failed rc {got.returncode}: {(got.stderr or '').strip()[:200]}", wd.FAILED)

    def do(self, action: str, f: Finding) -> str:
        from harness import watchdog as wd
        if action not in wd.ACTIONS:
            raise ValueError(f"not a watchdog action: {action}")
        from harness import monitor
        if action in MACHINE_ACTS and not monitor.live_home():
            return wd.Said(monitor.off_live(f"the watchdog's {action}"), wd.REFUSED)
        try:
            return wd.said(getattr(self, action)(f), action)
        except Exception as exc:  # noqa: BLE001 - one failed action must not cost the rest of the wake
            return wd.Said(f"{action} failed: {type(exc).__name__}: {exc}", wd.FAILED)
