"""`soh claude-news`: what changed in Claude Code since last time, relevant to this setup first. #866."""
from __future__ import annotations

import sys
from pathlib import Path

from harness.commands.common import emit, err, note


def cmd_claude_news(a, model=None, run=None, opener=None) -> int:
    from harness import claude_news as cn
    from harness import memory_store as ms

    kw_run = {"run": run} if run else {}
    try:
        text = (Path(a.changelog).read_text(encoding="utf-8") if a.changelog
                else cn.fetch(**({"opener": opener} if opener else {})))
    except (OSError, ValueError) as exc:
        return err(f"could not read the Claude Code changelog: {exc}")
    settings = Path(a.settings).expanduser() if a.settings else Path.home() / ".claude" / "settings.json"
    s = cn.setup(settings, cn.installed(**kw_run))
    conn = ms.connect()
    try:
        d = cn.digest(conn, text, s, model=model or cn.local_model, since=a.since or None,
                      keep=not a.no_record)
    finally:
        conn.close()
    if not d["versions"]:
        print(f"no Claude Code changes since {d['since'] or 'the newest version'}", file=sys.stderr)
        emit(**d, setup=s, notified=None)
        return 0
    for line in cn.render(d):
        note(line)
    sent = cn.notify(d, **kw_run) if a.notify else None
    if sent:
        note(f"\n{sent}")
    emit(**d, setup=s, notified=sent)
    return 0
