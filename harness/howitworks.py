"""The front page's "How it works" diagram: the Archify workflow model drawn as inline SVG. #584.

The model (how-it-works.workflow.json) is authored and validated with Archify;
this draws it in the site's own palette, once wide and once tall for a phone.
"""
from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from urllib.parse import quote

REPO_URL = "https://github.com/unxmaal/SoHoT"
MODEL = Path(__file__).resolve().parent / "how-it-works.workflow.json"

LABEL_EM, SUB_EM = 0.7, 0.52   # glyph advance of Silkscreen and Plex Sans, measured in Chrome
WIDE_TYPE = (12, 11, 13)       # label px, sublabel px, line height
TALL_TYPE = (13, 12, 15)

CSS = """
.flow { display:block; width:100%; height:auto; overflow:visible }
.flow.tall { display:none }
@media (max-width: 640px) {
  .flow.wide { display:none }
  .flow.tall { display:block; max-width:22rem; margin:0 auto }
}
.flow .shadow { fill:var(--shadow) }
.flow .node { stroke:var(--line); stroke-width:2 }
.flow .t-external .node { fill:var(--butter) }
.flow .t-backend .node { fill:var(--sand2) }
.flow .t-messagebus .node { fill:var(--tang) }
.flow .t-security .node { fill:var(--hot) }
.flow .t-database .node, .flow .t-cloud .node { fill:var(--turq) }
.flow .t-frontend .node { fill:var(--pool) }
.flow text { fill:var(--on) }
.flow .t-backend text { fill:var(--ink) }
.flow .nl { font:12px "Silkscreen",ui-monospace,monospace }
.flow .ns { font:11px "IBM Plex Sans",system-ui,sans-serif }
.flow.tall .nl { font-size:13px } .flow.tall .ns { font-size:12px }
.flow text.lane { font:11px "Silkscreen",ui-monospace,monospace; fill:var(--ink);
                  letter-spacing:.04em; paint-order:stroke; stroke:var(--sand); stroke-width:4px }
.flow .edge { fill:none; stroke:var(--line); stroke-width:2 }
.flow .edge.ret { stroke:var(--hot); stroke-width:2.5; stroke-dasharray:7 5 }
.flow .ahead { fill:var(--line) } .flow .ahead.ret { fill:var(--hot) }
.flow text.el { font:italic 600 11px "IBM Plex Sans",system-ui,sans-serif; fill:var(--ink);
                paint-order:stroke; stroke:var(--sand); stroke-width:4px }
.flow text.el.ret { fill:var(--hot) }
.flow a:hover .node, .flow a:focus-visible .node { stroke-width:3.5 }
.flow a:focus-visible { outline:none }
"""


def load(path: Path = MODEL) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _safe_path(p: str) -> bool:
    return bool(p) and not p.startswith(("/", "~", "\\")) and ".." not in p.split("/") \
        and ":" not in p and "\\" not in p


def href(model: dict, node: dict) -> str:
    """The node's first source as a GitHub blob at the model's pinned commit."""
    repo = model.get("meta", {}).get("repository") or {}
    if repo.get("url") != REPO_URL:
        raise ValueError(f"the model names {repo.get('url')!r}, not {REPO_URL}")
    rev = repo.get("revision") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", rev):
        raise ValueError(f"revision {rev!r} is not a full commit id")
    src = (node.get("sources") or [None])[0]
    if not src or not _safe_path(src.get("path", "")):
        raise ValueError(f"node {node.get('id')} has no repository-relative source")
    line, end = src.get("line"), src.get("end_line")
    frag = f"#L{line}" + (f"-L{end}" if end and end != line else "") if line else ""
    return f"{REPO_URL}/blob/{rev}/{quote(src['path'])}{frag}"


def _wrap(text: str, width: float, px: float, em: float) -> list[str]:
    per = max(4, int(width / (px * em)))
    lines, cur = [], ""
    for word in (text or "").split():
        if cur and len(cur) + 1 + len(word) > per:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


def _lane_order(model: dict) -> list[str]:
    return [l["id"] for l in model["lanes"]]


def _reversed(model: dict, lane: str) -> bool:
    """A lane whose own edges run right to left: the snake's return row."""
    nodes = {n["id"]: n for n in model["nodes"]}
    delta = sum(nodes[e["to"]]["col"] - nodes[e["from"]]["col"] for e in model["edges"]
                if nodes[e["from"]]["lane"] == lane == nodes[e["to"]]["lane"])
    return delta < 0


def _rows(n: dict, width: float, kind: tuple) -> list[tuple[str, str]]:
    lpx, spx, _ = kind
    return ([("nl", t) for t in _wrap(n["label"], width - 18, lpx, LABEL_EM)]
            + [("ns", t) for t in _wrap(n.get("sublabel", ""), width - 18, spx, SUB_EM)])


def _height(model: dict, width: float, kind: tuple) -> float:
    return max(len(_rows(n, width, kind)) for n in model["nodes"]) * kind[2] + 18


def _node(n: dict, box: tuple, url: str, kind: tuple) -> str:
    x, y, w, h = box
    line = kind[2]
    rows = _rows(n, w, kind)
    top = y + (h - len(rows) * line) / 2 + line - 3
    texts = "".join(f'<text class="{c}" x="{x + 10:g}" y="{top + i * line:g}">{escape(t)}</text>'
                    for i, (c, t) in enumerate(rows))
    aria = escape(f"{n['label']}: {n.get('sublabel', '')} (source)", quote=True)
    return (f'<a href="{escape(url, quote=True)}" class="t-{escape(n["type"])}" '
            f'aria-label="{aria}"><rect class="shadow" x="{x + 4:g}" y="{y + 4:g}" '
            f'width="{w:g}" height="{h:g}"/><rect class="node" x="{x:g}" y="{y:g}" '
            f'width="{w:g}" height="{h:g}"/>{texts}</a>')


def _defs(suffix: str) -> str:
    return "".join(
        f'<marker id="{name}-{suffix}" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0 0L10 5L0 10z" class="ahead{cls}"/></marker>'
        for name, cls in (("ah", ""), ("ahr", " ret")))


def _edge(e: dict, d: str, suffix: str, label: str = "") -> str:
    ret = e.get("role") == "return"
    return (f'<path class="edge{" ret" if ret else ""}" data-edge="{escape(e["id"])}" d="{d}" '
            f'marker-end="url(#{"ahr" if ret else "ah"}-{suffix})"/>{label}')


def _label(e: dict, x: float, y: float, anchor: str = "start", rotate: bool = False) -> str:
    if not e.get("label"):
        return ""
    ret = " ret" if e.get("role") == "return" else ""
    rot = f' transform="rotate(-90 {x:g} {y:g})"' if rotate else ""
    return (f'<text class="el{ret}" x="{x:g}" y="{y:g}" text-anchor="{anchor}"{rot}>'
            f'{escape(e["label"])}</text>')


# --- wide: lanes are rows, the third runs right to left ----------------------

W_LEFT, W_PITCH, W_NODE, W_GAP, W_HEAD = 44, 192, 162, 46, 26


def wide(model: dict) -> str:
    lanes = _lane_order(model)
    nodes = {n["id"]: n for n in model["nodes"]}
    h = _height(model, W_NODE, WIDE_TYPE)
    row = W_HEAD + h + W_GAP
    cols = max(n["col"] for n in model["nodes"])
    width = W_LEFT + cols * W_PITCH + W_NODE + 20

    def box(n):
        i = lanes.index(n["lane"])
        return (W_LEFT + n["col"] * W_PITCH, 10 + i * row + W_HEAD, W_NODE, h)

    edges = []
    for e in model["edges"]:
        a, b = nodes[e["from"]], nodes[e["to"]]
        ax, ay, _, _ = box(a)
        bx, by, _, _ = box(b)
        amid, bmid = ay + h / 2, by + h / 2
        acx, bcx = ax + W_NODE / 2, bx + W_NODE / 2
        if e.get("role") == "return":
            ch = W_LEFT - 26
            d = f"M{ax:g} {amid:g}H{ch:g}V{bmid:g}H{bx:g}"
            edges.append(_edge(e, d, "w", _label(e, ax - 14, amid - 7, "end")))
        elif a["lane"] == b["lane"]:
            x1, x2 = (ax + W_NODE, bx) if b["col"] > a["col"] else (ax, bx + W_NODE)
            edges.append(_edge(e, f"M{x1:g} {amid:g}H{x2:g}", "w",
                               _label(e, (x1 + x2) / 2, amid - 7, "middle")))
        elif a["col"] == b["col"]:
            edges.append(_edge(e, f"M{acx:g} {ay + h:g}V{by:g}", "w",
                               _label(e, acx + 8, (ay + h + by) / 2 + 4)))
        else:
            gy = by - W_HEAD - W_GAP / 2
            edges.append(_edge(e, f"M{acx:g} {ay + h:g}V{gy:g}H{bcx:g}V{by:g}", "w",
                               _label(e, (acx + bcx) / 2, gy - 6, "middle")))

    heads = []
    for i, lane in enumerate(model["lanes"]):
        text = f"{i + 1}. {lane['label']}"
        y = 10 + i * row + 17
        entered = [box(nodes[e["to"]])[0] for e in model["edges"]
                   if nodes[e["to"]]["lane"] == lane["id"] != nodes[e["from"]]["lane"]
                   and e.get("role") != "return"]
        span = len(text) * 11 * LABEL_EM
        left = not any(x < W_LEFT + span + 8 for x in entered)
        x, anchor = (W_LEFT, "start") if left else (width - 20, "end")
        heads.append(f'<text class="lane" x="{x:g}" y="{y:g}" text-anchor="{anchor}">'
                     f'{escape(text)}</text>')

    body = "".join(_node(n, box(n), href(model, n), WIDE_TYPE) for n in model["nodes"])
    height = 10 + len(lanes) * row - W_GAP + 14
    return (f'<svg class="flow wide" viewBox="0 0 {width:g} {height:g}" role="group" '
            f'aria-label="{escape(model["meta"]["title"], quote=True)}">'
            f'<defs>{_defs("w")}</defs>{"".join(edges)}{"".join(heads)}{body}</svg>')


# --- tall: one column for a phone ------------------------------------------

T_X, T_NODE, T_GAP, T_HEAD, T_WIDTH = 34, 232, 26, 28, 320


def tall(model: dict) -> str:
    lanes = _lane_order(model)
    T_H = _height(model, T_NODE, TALL_TYPE)
    order = []
    for lane in lanes:
        members = sorted((n for n in model["nodes"] if n["lane"] == lane), key=lambda n: n["col"],
                         reverse=_reversed(model, lane))
        order += members
    pos, heads, y = {}, [], 8
    for i, lane in enumerate(model["lanes"]):
        y += T_HEAD
        heads.append(f'<text class="lane" x="{T_X:g}" y="{y - 9:g}">'
                     f'{escape(f"{i + 1}. {lane["label"]}")}</text>')
        for n in (m for m in order if m["lane"] == lane["id"]):
            pos[n["id"]] = y
            y += T_H + T_GAP
    index = {n["id"]: i for i, n in enumerate(order)}
    stub = T_X + T_NODE - 28
    right = T_X + T_NODE
    channels: dict[str, float] = {}
    edges = []
    for e in model["edges"]:
        ay, by = pos[e["from"]], pos[e["to"]]
        amid, bmid = ay + T_H / 2, by + T_H / 2
        if e.get("role") == "return":
            ch = T_X - 20
            d = f"M{T_X:g} {amid:g}H{ch:g}V{bmid:g}H{T_X:g}"
            edges.append(_edge(e, d, "t", _label(e, ch - 4, (amid + bmid) / 2, "middle", True)))
        elif index[e["to"]] == index[e["from"]] + 1:
            edges.append(_edge(e, f"M{stub:g} {ay + T_H:g}V{by:g}", "t",
                               _label(e, stub + 7, (ay + T_H + by) / 2 + 4)))
        else:
            ch = channels.setdefault(e["to"], right + 18 + 18 * len(set(channels.values())))
            d = f"M{right:g} {amid:g}H{ch:g}V{bmid:g}H{right:g}"
            edges.append(_edge(e, d, "t", _label(e, ch - 5, (amid + bmid) / 2, "middle", True)))
    body = "".join(_node(n, (T_X, pos[n["id"]], T_NODE, T_H), href(model, n), TALL_TYPE)
                   for n in order)
    return (f'<svg class="flow tall" viewBox="0 0 {T_WIDTH:g} {y - T_GAP + 12:g}" role="group" '
            f'aria-label="{escape(model["meta"]["title"], quote=True)}">'
            f'<defs>{_defs("t")}</defs>{"".join(edges)}{"".join(heads)}{body}</svg>')


def diagram(model: dict | None = None) -> str:
    """Both layouts; CSS shows the one that fits. Raises ValueError on an unsafe link."""
    model = load() if model is None else model
    return wide(model) + tall(model)
