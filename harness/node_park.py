"""Park or unpark one node in nodes.yaml by editing its parked line, never its other lines (#2135)."""
from __future__ import annotations

import os
import re
from pathlib import Path

_NAME = re.compile(r"^(\s*)-\s+name:\s*['\"]?([^'\"#\s]+)['\"]?\s*(?:#.*)?$")
_ANY_ITEM = re.compile(r"^\s*-\s+\S")
_PARKED = re.compile(r"^(\s*parked:\s*)(?:true|false)(\s*(?:#.*)?)$")


def set_parked(name: str, parked: bool, file=None) -> dict:
    """{node, parked, changed, file}: the node's `parked:` line set, the file replaced in one rename; ValueError when it cannot be set."""
    import yaml

    from harness import atomic_file, nodes
    where = Path(file) if file else nodes.path()
    try:
        text = where.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"no nodes file at {where}") from None
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if (m := _NAME.match(ln.rstrip("\r\n"))) and m.group(2) == name]
    if len(starts) != 1:
        raise ValueError(f"{name!r} is not one `- name:` entry of {where.name}" if not starts else f"{name!r} is named twice in {where.name}")
    first = starts[0]
    key_indent = " " * (len(_NAME.match(lines[first].rstrip("\r\n")).group(1)) + 2)
    end = next((i for i in range(first + 1, len(lines)) if _ANY_ITEM.match(lines[i]) and not lines[i].startswith(key_indent)), len(lines))
    word = "true" if parked else "false"
    at = next((i for i in range(first + 1, end) if lines[i].startswith(key_indent) and _PARKED.match(lines[i].rstrip("\r\n"))), None)
    if at is not None:
        m = _PARKED.match(lines[at].rstrip("\r\n"))
        lines[at] = f"{m.group(1)}{word}{m.group(2)}" + lines[at][len(lines[at].rstrip("\r\n")):]
    elif parked:
        newline = lines[first][len(lines[first].rstrip("\r\n")):] or "\n"
        if not lines[first].endswith(("\n", "\r")):
            lines[first] += newline
        lines.insert(first + 1, f"{key_indent}parked: true{newline}")
    new = "".join(lines)
    got = {n.name: n for n in nodes.parse(yaml.safe_load(new) or {}, str(where))}
    if name not in got or got[name].parked != parked:
        raise ValueError(f"{name!r}: the edit would not leave it {'parked' if parked else 'unparked'}; {where.name} is unchanged")
    if new == text:
        return {"node": name, "parked": parked, "changed": False, "file": str(where)}
    tmp = where.with_name(where.name + f".{os.getpid()}.tmp")
    tmp.write_text(new, encoding="utf-8")
    atomic_file.replace(tmp, where)
    return {"node": name, "parked": parked, "changed": True, "file": str(where)}
