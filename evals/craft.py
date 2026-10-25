"""The craft lane: a model drives VectorCraft or FigCraft over the app's own MCP server; graded from the app's document (#1209)."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from evals import craft_check, craft_mcp, sandbox
from harness import cuts

#: Seconds one tool call, a headless build or a version probe may take.
CALL_TIMEOUT_S = 30.0
#: Tool calls a case may make in all.
MAX_TOOL_CALLS = 80
#: Characters of one tool result the model is shown.
OUTPUT_CAP = 16_000
#: Document units a position or size may sit off its target.
GEOMETRY_TOLERANCE_PX = 1.0
#: Mean RGB difference from the reference render a passing render may show; reported, never the pass.
RENDER_DIFFERENCE_MAX = 0.01

HARNESS_DIR = "_harness"
RENDER = "render.png"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"(\d+\.\d+\.\d+[\w.+-]*)")


class CraftError(RuntimeError):
    """The app could not be run, or did not answer as its release does."""


class PinError(CraftError):
    """The installed app is not the release a run book was validated on."""


def _vc_points(n: dict, b: dict):
    anchors = n.get("anchors")
    if isinstance(anchors, list) and len(anchors) >= 2:
        pts = [(a.get("x"), a.get("y")) if isinstance(a, dict) else tuple(a[:2]) for a in anchors]
        if all(isinstance(v, (int, float)) for p in pts for v in p):
            return [list(p) for p in pts]
    if not all(isinstance(b.get(k), (int, float)) for k in ("x", "y", "width", "height")):
        return []
    x, y, w, h = b["x"], b["y"], b["width"], b["height"]
    return [[x, y + h / 2], [x + w, y + h / 2]] if w >= h else [[x + w / 2, y], [x + w / 2, y + h]]


def _color(paint):
    if isinstance(paint, dict):
        paint = paint.get("color") or paint.get("hex")
    return paint if isinstance(paint, str) else None


def normalize_vectorcraft(doc: dict) -> list[dict]:
    """VectorCraft's document.inspect as checker nodes: bounds are geometry, the children tree is the parent."""
    kinds = {"rectangle": "rect", "type": "text", "line": "line"}
    out: list[dict] = []

    def walk(nodes, parent):
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            kind = str(n.get("kind") or "").lower()
            b = n.get("bounds") or {}
            node = {"id": n.get("id"), "type": kinds.get(kind, kind), "name": n.get("name") or "", "parent": parent,
                    "x": b.get("x"), "y": b.get("y"), "w": b.get("width"), "h": b.get("height"),
                    "fill": _color(n.get("fill")), "stroke": _color(n.get("stroke")), "text": n.get("text")}
            anchors = n.get("anchors")
            count = len(anchors) if isinstance(anchors, list) else anchors
            if kind == "line" or (kind == "path" and count == 2 and not n.get("closed")):
                node["type"], node["points"] = "line", _vc_points(n, b)
            out.append(node)
            walk(n.get("children"), n.get("id"))

    walk(doc.get("layers") or doc.get("nodes"), None)
    return out


def _even(value):
    """One number for a padding given as a number, a list or a dict of equal sides; None when they differ."""
    if isinstance(value, (int, float)):
        return value
    sides = list(value.values()) if isinstance(value, dict) else value if isinstance(value, list) else []
    return sides[0] if sides and all(s == sides[0] for s in sides) else None


def _fig_layout(n: dict):
    raw = n.get("layout")
    if raw in (None, "", "none", False):
        return None
    if isinstance(raw, str):
        raw = {"mode": raw}
    if not isinstance(raw, dict):
        return None
    mode = raw.get("mode") or raw.get("direction") or raw.get("layoutMode")
    gap = raw.get("gap", raw.get("itemSpacing", n.get("gap")))
    pad = raw.get("padding", n.get("padding"))
    if pad is None and "paddingTop" in raw:
        pad = [raw.get(f"padding{s}") for s in ("Top", "Right", "Bottom", "Left")]
    return {"mode": str(mode).lower() if mode else None, "gap": gap, "padding": _even(pad)}


def normalize_figcraft(doc: dict) -> list[dict]:
    """FigCraft's document.inspect as checker nodes: absoluteBounds are geometry, an image fill makes an image."""
    out: list[dict] = []

    def walk(nodes, parent):
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            ab = n.get("absoluteBounds") or {}
            fills = [f for f in n.get("fills") or [] if isinstance(f, dict)]
            image = next((f for f in fills if f.get("type") == "image"), None)
            solid = next((f for f in fills if f.get("type") == "solid"), None)
            radius = n.get("cornerRadius")
            node = {"id": n.get("id"), "type": "image" if image else str(n.get("type") or "").lower(),
                    "name": n.get("name") or "", "parent": parent,
                    "x": ab.get("x", n.get("x")), "y": ab.get("y", n.get("y")),
                    "w": ab.get("width", n.get("width")), "h": ab.get("height", n.get("height")),
                    "fill": _color(solid), "corner_radius": _even(radius) if radius is not None else None,
                    "text": n.get("characters"), "font_size": n.get("fontSize"), "font_style": n.get("fontStyle"),
                    "font_family": n.get("fontFamily"), "layout": _fig_layout(n)}
            if image:
                node["image"] = {"fit": image.get("scale_mode") or image.get("scaleMode")}
            out.append(node)
            walk(n.get("children"), n.get("id"))

    walk(doc.get("pages"), None)
    return out


@dataclass(frozen=True)
class App:
    name: str
    cli: str
    #: The tool a harness call goes through, and the command reading the document.
    inspect: tuple
    normalize: object
    #: Environment the app runs with, for renders that match across machines.
    env: tuple = ()
    #: Page the reference render is taken of in a fresh headless document; None renders the artboard.
    fresh_page: object = None

    def server_args(self, root: Path) -> list[str]:
        return ["mcp", "--automation-read-root", str(root), "--automation-write-root", str(root)]

    def run_args(self, script: Path, root: Path) -> list[str]:
        if self.name == "vectorcraft":
            return ["run", "--commands", str(script)]
        return ["run", str(script), "--automation-read-root", str(root), "--automation-write-root", str(root)]

    def render_step(self, path: str, page=None) -> dict:
        if self.name == "vectorcraft":
            return {"command": "document.export", "params": {"path": path}}
        page = self.fresh_page if page is None else page
        return {"command": "file.export", "params": {"ids": [page], "format": "png", "path": path}}

    def environ(self) -> dict:
        return {**os.environ, **dict(self.env)}


APPS = {
    "vectorcraft": App("vectorcraft", "vectorcraft-cli", ("document.inspect", {"depth": 32, "childLimit": 1000}),
                       normalize_vectorcraft),
    "figcraft": App("figcraft", "figcraft-cli", ("document.inspect", {"depth": 32}), normalize_figcraft,
                    env=(("FIGCRAFT_NO_SYSTEM_FONTS", "1"),), fresh_page=1),
}


def app_of(case) -> App:
    return APPS[case.params["app"]]


def binary(app: App) -> list[str] | None:
    """The argv prefix that runs an app's CLI: SOHOT_<APP>_CLI, else the CLI on PATH; None when neither."""
    named = os.environ.get(f"SOHOT_{app.name.upper()}_CLI", "").strip()
    found = named if named and Path(named).is_file() else shutil.which(app.cli)
    return [found] if found else None


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def installed_version(argv: list[str]) -> str:
    try:
        done = subprocess.run([*argv, "--version"], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=CALL_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        cuts.cut("craft_call_timeout", f"{argv[-1]} --version timed out", kept=0, dropped=1)
        raise CraftError(f"{argv[-1]} --version took over {CALL_TIMEOUT_S:g}s") from exc
    except OSError as exc:
        raise CraftError(f"could not run {argv[-1]}: {exc}") from exc
    m = _VERSION.search(done.stdout or "")
    if done.returncode != 0 or m is None:
        raise CraftError(f"{argv[-1]} --version said {(done.stdout or done.stderr).strip()[:120]!r}")
    return m.group(1)


def check_pin(case, argv: list[str]) -> dict:
    """The pinned release when the installed CLI is it; PinError naming the pin otherwise."""
    app, rel = app_of(case), case.params["release"]
    got = installed_version(argv)
    pin = f"{app.name} {rel['tag']} ({rel['asset']}, sha256 {rel['sha256']})"
    advice = ("command ids change between releases, so revalidate its reference script with "
              "`soh craft validate --revalidate` and update the pin before any candidate runs")
    if got != str(rel["version"]):
        raise PinError(f"{app.cli} {got} is installed, but {case.id} is pinned to {pin}; {advice}")
    want = rel.get("binary_sha256")
    if want:
        have = file_sha256(Path(argv[0]))
        if have != want:
            raise PinError(f"{argv[0]} has sha256 {have}, but {case.id} is pinned to {pin} with binary sha256 "
                           f"{want}; {advice}")
    return {"app": app.name, "version": got, "tag": rel["tag"], "asset": rel["asset"], "sha256": rel["sha256"]}


def _steps(path: Path) -> list[dict]:
    steps = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(steps, list) or not steps or not all(
            isinstance(s, dict) and set(s) <= {"command", "params"} and isinstance(s.get("command"), str)
            and isinstance(s.get("params", {}), dict) for s in steps):
        raise ValueError(f"{path.name}: a reference script is a non-empty list of {{command, params}}")
    return steps


def reference_steps(case) -> list[dict]:
    return _steps(Path(case.source).parent / case.params["reference"])


def validate_case(path: Path, params: dict, assertions: dict) -> dict:
    """Refuse a run book the runner could not pin, build or grade; pin its script and assets into the digest."""
    name = Path(path).name
    if params.get("app") not in APPS:
        raise ValueError(f"{name}: params.app must be one of {', '.join(APPS)}")
    rel = params.get("release") or {}
    missing = [k for k in ("version", "tag", "asset", "sha256") if not rel.get(k)]
    if missing or not _HEX64.match(str(rel.get("sha256"))):
        raise ValueError(f"{name}: params.release needs version, tag, asset and a sha256 from SHA256SUMS.txt")
    if not isinstance(params.get("max_steps"), int) or params["max_steps"] < 1:
        raise ValueError(f"{name}: a craft case names its max_steps")
    here = Path(path).parent
    script = here / str(params.get("reference") or "")
    if not params.get("reference") or not script.is_file():
        raise ValueError(f"{name}: params.reference must name the app's own command script")
    steps = _steps(script)
    h = hashlib.sha256(script.read_bytes().replace(b"\r\n", b"\n"))
    for asset in params.get("assets") or []:
        p = here / asset
        if ".." in Path(asset).parts or not p.is_file():
            raise ValueError(f"{name}: asset {asset} is not a file beside the case")
        h.update(asset.encode("utf-8") + b"\x00" + p.read_bytes())
    spec = (assertions.get("craft") or {}).get("requirements")
    try:
        craft_check.validate(spec)
    except ValueError as exc:
        raise ValueError(f"{name}: {exc}") from exc
    ids = {r["id"] for r in spec}
    for control, c in (params.get("controls") or {}).items():
        step = c.get("step")
        if not isinstance(step, int) or not 0 <= step < len(steps):
            raise ValueError(f"{name}: control {control} names no step of the reference script")
        unknown = set(c.get("set") or {}) - set(steps[step].get("params") or {})
        if not c.get("set") or unknown:
            raise ValueError(f"{name}: control {control} must change params step {step} has; not {sorted(unknown)}")
        if not c.get("fails") or set(c["fails"]) - ids:
            raise ValueError(f"{name}: control {control} must name the requirements it fails, from {sorted(ids)}")
    return {"craft_digest": h.hexdigest()[:16]}


def controls(case) -> dict[str, tuple[list, list]]:
    """name -> (steps, requirement ids it must fail): the reference, an empty document, and each planted near-miss."""
    ref = reference_steps(case)
    out = {"reference": (ref, []), "empty": ([], None)}
    for name, c in (case.params.get("controls") or {}).items():
        steps = copy.deepcopy(ref)
        steps[c["step"]]["params"].update(c["set"])
        out[name] = (steps, list(c["fails"]))
    return out


def scratch(case, prefix: str = "soh-craft-") -> Path:
    """A fresh working folder holding the run book's assets, resolved so the app's roots match it."""
    root = Path(os.path.realpath(tempfile.mkdtemp(prefix=prefix)))
    for asset in case.params.get("assets") or []:
        shutil.copy2(Path(case.source).parent / asset, root / Path(asset).name)
    (root / HARNESS_DIR).mkdir()
    return root


def _documents(lines: str) -> list:
    """Every step result a headless run printed that is a document, in order."""
    found = []
    for line in lines.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        got = rec.get("result") if isinstance(rec, dict) else None
        if isinstance(got, dict) and any(k in got for k in ("layers", "pages", "artboards")):
            found.append(got)
    return found


def headless(case, argv: list[str], steps: list[dict], root: Path) -> dict:
    """Run `steps` with `<app>-cli run`, then render and inspect; the document and the render's path."""
    app = app_of(case)
    render = f"{HARNESS_DIR}/{RENDER}"
    script = root / HARNESS_DIR / "script.json"
    cmd, params = app.inspect
    script.write_text(json.dumps([*steps, app.render_step(render), {"command": cmd, "params": params}]),
                      encoding="utf-8")
    try:
        done = subprocess.run([*argv, *app.run_args(script, root)], cwd=root, env=app.environ(),
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=CALL_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        cuts.cut("craft_call_timeout", f"a headless {app.name} build timed out", kept=0, dropped=1)
        raise CraftError(f"{app.cli} run took over {CALL_TIMEOUT_S:g}s") from exc
    except OSError as exc:
        raise CraftError(f"could not run {app.cli}: {exc}") from exc
    docs = _documents(done.stdout or "")
    if done.returncode != 0 or not docs:
        tail = (done.stderr or done.stdout or "").strip()[-300:]
        raise CraftError(f"{app.cli} run exited {done.returncode}: {tail}")
    return {"document": docs[-1], "render": root / render}


def grade(case, document: dict, root: Path, render: Path | None, reference_render: Path | None) -> dict:
    """The per-requirement verdict on a document, the exported files in `root`, and the render beside the reference's."""
    nodes = app_of(case).normalize(document)
    got = craft_check.check(case.assertions["craft"]["requirements"], nodes, GEOMETRY_TOLERANCE_PX, root)
    diff = None
    if render is not None and reference_render is not None and Path(render).is_file() \
            and Path(reference_render).is_file():
        diff = craft_check.render_difference(render, reference_render)
    failed = [r["id"] for r in got["requirements"] if not r["passed"]]
    got["render_difference"] = diff
    got["render_ok"] = diff is not None and diff <= RENDER_DIFFERENCE_MAX
    got["detail"] = (f"{got['met']} of {got['total']} requirements met" + (f"; failed: {', '.join(failed)}"
                     if failed else "") + ("" if diff is None or got["render_ok"]
                                           else f"; render differs from the reference by {diff:g}"))
    return got


def validate(case, argv: list[str], record: Path | None = None) -> list[dict]:
    """Build every control headless and grade it: the reference must pass, the rest must fail as named."""
    out = []
    for name, (steps, fails) in controls(case).items():
        root = scratch(case, prefix=f"soh-craft-{name}-")
        try:
            built = headless(case, argv, steps, root)
            got = grade(case, built["document"], root, None, None)
            if record is not None:
                record.mkdir(parents=True, exist_ok=True)
                (record / f"{case.id}.{name}.inspect.json").write_text(
                    json.dumps(built["document"], indent=1) + "\n", encoding="utf-8")
        finally:
            shutil.rmtree(root, ignore_errors=True)
        failed = [r["id"] for r in got["requirements"] if not r["passed"]]
        if name == "reference":
            ok = got["passed"]
        elif fails is None:
            ok = not got["passed"]
        else:
            ok = not got["passed"] and set(fails) <= set(failed)
        out.append({"case": case.id, "control": name, "ok": ok, "passed": got["passed"], "failed": failed,
                    "expected": fails, "detail": got["detail"]})
    return out


class Session:
    """The app's MCP server for one case, with the sandbox's Call validity on every tool call."""

    def __init__(self, case, argv: list[str], root: Path, cap: int | None = None):
        self.app, self.root = app_of(case), root
        self.cap = MAX_TOOL_CALLS if cap is None else cap
        self.calls = 0
        self.capped = False
        self.client = craft_mcp.Client([*argv, *self.app.server_args(root)], cwd=root, env=self.app.environ(),
                                       stderr=root / HARNESS_DIR / "server.log")
        try:
            self.client.initialize(CALL_TIMEOUT_S)
            self.listed = {t["name"]: t for t in self.client.tools(CALL_TIMEOUT_S) if t.get("name")}
        except craft_mcp.McpError:
            self.client.close()
            raise

    @property
    def tools(self) -> tuple:
        return tuple(self.listed)

    def openai_tools(self) -> list[dict]:
        return [{"type": "function", "function": {
            "name": n, "description": t.get("description") or "",
            "parameters": t.get("inputSchema") or {"type": "object", "properties": {}}}} for n, t in self.listed.items()]

    def call(self, name, arguments) -> tuple[sandbox.Call, str]:
        """Validate and send one model tool call; never raises on the model's input."""
        raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
        call = sandbox.Call(str(name), raw)
        if self.calls >= self.cap:
            self.capped = True
            call.why = f"tool-call cap of {self.cap} reached"
            return call, f"error: {call.why}"
        self.calls += 1
        if name not in self.listed:
            call.why = f"unknown tool {name!r}"
            return call, f"error: {call.why}; the server lists {', '.join(self.listed)}"
        call.real = True
        try:
            args = json.loads(raw) if raw.strip() else {}
        except ValueError as exc:
            call.why = f"arguments are not JSON: {exc}"
            return call, f"error: {call.why}"
        if not isinstance(args, dict):
            call.why = "arguments must be a JSON object"
            return call, f"error: {call.why}"
        call.parsed = True
        problem = _schema_problem(self.listed[name].get("inputSchema") or {}, args)
        if problem:
            call.why = problem
            return call, f"error: {problem}"
        call.schema_ok = True
        try:
            result = self.client.call(name, args, CALL_TIMEOUT_S)
        except craft_mcp.McpTimeout as exc:
            cuts.cut("craft_call_timeout", f"a {self.app.name} tool call timed out", kept=0, dropped=1)
            call.why = str(exc)
            return call, f"error: {exc}"
        except craft_mcp.McpError as exc:
            call.why = str(exc)
            return call, f"error: {exc}"
        text = craft_mcp.text_of(result)
        call.ok = not result.get("isError")
        if not call.ok:
            call.why = text[:300]
        if len(text) > OUTPUT_CAP:
            cuts.cut("craft_output_cap", f"a {self.app.name} tool result kept its first {OUTPUT_CAP} characters",
                     kept=OUTPUT_CAP, dropped=len(text) - OUTPUT_CAP)
            text = text[:OUTPUT_CAP] + f"\n...[{len(text) - OUTPUT_CAP} more characters not shown]"
        return call, text

    def run(self, command: str, params: dict):
        """One harness command through run_command, not counted against the model; its JSON result."""
        result = self.client.call("run_command", {"command": command, "params": params}, CALL_TIMEOUT_S)
        if result.get("isError"):
            raise CraftError(f"{command}: {craft_mcp.text_of(result)[:300]}")
        return craft_mcp.json_of(result)

    def finish(self) -> dict:
        """Inspect the document as the model left it, then render it beside where the reference was rendered."""
        cmd, params = self.app.inspect
        document = self.run(cmd, params)
        if not isinstance(document, dict):
            raise CraftError(f"{cmd} answered with no document")
        render = f"{HARNESS_DIR}/{RENDER}"
        page = None
        if self.app.fresh_page is not None:
            pages = document.get("pages") or []
            page = document.get("currentPage") if isinstance(document.get("currentPage"), int) else (
                pages[0].get("id") if pages and isinstance(pages[0], dict) else self.app.fresh_page)
        step = self.app.render_step(render, page)
        try:
            self.run(step["command"], step["params"])
            unrendered = ""
        except (CraftError, craft_mcp.McpError) as exc:
            unrendered = str(exc)[:300]
        return {"document": document, "render": self.root / render, "render_error": unrendered}

    def cleanup(self) -> None:
        self.client.close()


def _schema_problem(schema: dict, args: dict) -> str:
    """Why `args` does not fit a tool's input schema at its top level, or ""."""
    props = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in args:
            return f"missing required argument {key!r}"
    if schema.get("additionalProperties") is False:
        extra = sorted(set(args) - set(props))
        if extra:
            return f"unexpected argument {extra[0]!r}"
    return ""
