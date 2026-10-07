"""`soh chaos`: run fault scenarios on a scratch home and report pass or fail per scenario. #492."""
from __future__ import annotations

from harness import paths
from harness.commands.common import emit, err, note


def cmd_chaos(a) -> int:
    from harness import chaos, exclusive
    env, modules = chaos.environment()
    why = chaos.refusal(bool(getattr(a, "yes_break_things", False)), env, modules)
    if why:
        return err(why)
    with chaos.machine_lock() as got:
        if not got:
            return err(f"refusing: the machine lock is held by "
                       f"{exclusive.describe(exclusive.holder())}; chaos runs "
                       f"only on an idle machine")
        scenarios = chaos.default_scenarios()
        only = list(getattr(a, "only", None) or [])
        if only:
            known = [s.name for s in scenarios]
            unknown = [n for n in only if n not in known]
            if unknown:
                return err(f"no scenario named {', '.join(unknown)}; "
                           f"known: {', '.join(known)}")
            scenarios = [s for s in scenarios if s.name in only]
        try:
            results = chaos.run_all(scenarios, live=paths.home(),
                                    parent=chaos.SCRATCH_PARENT, note=note)
        except chaos.ChaosRefused as exc:
            return err(f"refusing: {exc}")
    for r in results:
        note(f"{'PASS' if r.ok else 'FAIL'}  {r.name}: {r.detail}")
    ok = all(r.ok for r in results)
    emit(ok=ok, results=[r._asdict() for r in results])
    return 0 if ok else 1
