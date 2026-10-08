"""`soh volume stop|start|status` and `soh disk speed`. #612."""
from __future__ import annotations

from harness.commands.common import emit, err, note


def _holder_lines(found) -> list[str]:
    return [f"  pid {p:<7} {c:<16} {n}" for p, c, n in found]


def cmd_volume(a) -> int:
    from harness import volume
    if not volume.supported():
        return err("soh volume is macOS-only: it stops launchd services and reads lsof. "
                   "`soh disk speed` works on every platform.")
    ops = volume.default_ops()
    try:
        if a.action == "start":
            got = volume.start(ops)
            for label in got["started"]:
                note(f"loaded {label}")
            note("queue resumed" if got["resumed"] else "queue left paused, as it was before stop")
            emit(**got)
            return 0
        vol = volume.volume_of(a.path) if a.path else volume.default_volume()
        if a.action == "status":
            got = volume.status(vol, ops)
            note(f"{vol}: {'mounted' if got['mounted'] else 'NOT mounted'}")
            note("services holding files: " + (", ".join(got["services"]) or "none"))
            for line in _holder_lines((h["pid"], h["command"], h["path"]) for h in got["holders"]):
                note(line)
            if got["stopped"]:
                note(f"stopped by `soh volume stop` at {got['stopped']['at']}: "
                     + (", ".join(got["stopped"]["stopped"]) or "nothing"))
            emit(**got)
            return 0
        note("pausing the queue and waiting for any running job to finish")
        got = volume.stop(vol, ops)
    except volume.VolumeError as exc:
        return err(str(exc))
    for label in got["stopped"]:
        note(f"stopped {label}")
    note(f"recorded in {volume.state_path()}")
    if got["remaining"]:
        return err(f"NOT SAFE: these processes still have files open on {vol}:\n"
                   + "\n".join(_holder_lines(got["remaining"])))
    note(f"nothing has files open on {vol}; safe to eject")
    emit(**got)
    return 0


def cmd_disk_speed(a) -> int:
    from harness import volume
    try:
        path = a.path or volume.default_volume()
        row = volume.speed(path, size=int(a.mib) * 1024 * 1024)
    except (volume.VolumeError, OSError) as exc:
        return err(str(exc))
    dev = row["device"]
    note(f"{row['volume']} ({', '.join(f'{k}={v}' for k, v in dev.items()) or 'device unknown'})")
    note(f"  read  {row['read_bytes_per_s'] / 1e6:,.0f} MB/s  write {row['write_bytes_per_s'] / 1e6:,.0f} MB/s")
    note(f"  {row['bytes'] / 1e9:.2f} GB in {row['block'] // 1024 // 1024} MiB blocks, "
         f"{row['method']}, at {row['path']}")
    note(f"  stored in {volume.speed_log()}")
    emit(measurement=row)
    return 0
