"""Stand-in vectorcraft-cli/figcraft-cli (--version, run, mcp) answering from the inspect fixtures, controls applied (#1209)."""
import copy
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSIONS = {"vectorcraft": "0.17.0", "figcraft": "0.11.2"}
HARNESS = {"document.inspect", "document.export", "file.export"}


def fixture(app, name):
    return json.loads((HERE / f"{app}-{name}.inspect.json").read_text(encoding="utf-8"))


def walk(nodes):
    for n in nodes or []:
        yield n
        yield from walk(n.get("children"))


class Doc:
    def __init__(self, app):
        self.app, self.steps = app, []

    def apply(self, command, params):
        if command not in HARNESS:
            self.steps.append((command, params))

    def document(self):
        if not self.steps:
            return fixture(self.app, "empty")
        doc = fixture(self.app, "svg-pipeline" if self.app == "vectorcraft" else "image-card")
        roots = doc.get("layers") or doc.get("pages")
        by_name = {n.get("name"): n for n in walk(roots)}
        if self.app == "vectorcraft":
            rects = [p for c, p in self.steps if c == "shape.rectangle"]
            texts = [p for c, p in self.steps if c == "text.create"]
            for name, p in zip(("Box A", "Box B", "Box C"), rects):
                by_name[name]["bounds"] = {"x": p["x"], "y": p["y"], "width": p["width"], "height": p["height"]}
            for name, p in zip(("Label A", "Label B", "Label C"), texts):
                by_name[name]["text"] = p["text"]
        else:
            for c, p in self.steps:
                if c == "image.place":
                    by_name["Photo"]["height"] = by_name["Photo"]["absoluteBounds"]["height"] = p["height"]
            texts = [p for c, p in self.steps if c == "node.create" and p.get("type") == "text"]
            for name, p in zip(("Heading", "Caption"), texts):
                by_name[name]["characters"] = p["text"]
        return doc

    def export(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".svg":
            path.write_text("<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            return
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (640, 480), "white")
        draw = ImageDraw.Draw(im)
        for n in walk((self.document().get("layers") or self.document().get("pages"))):
            box = n.get("absoluteBounds") or n.get("bounds") or {}
            if n.get("kind") == "Rectangle" or n.get("name") == "Photo":
                draw.rectangle([box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"]], fill="black")
        im.save(path)

    def run(self, command, params):
        if command == "boom":
            raise ValueError("boom is not a command")
        self.apply(command, params)
        if command == "document.inspect":
            return self.document()
        if command in ("document.export", "file.export"):
            self.export(params["path"])
            return {"path": params["path"]}
        return {"id": len(self.steps) + 1}


def run(app, args):
    script = args[args.index("--commands") + 1] if "--commands" in args else args[0]
    doc = Doc(app)
    for i, step in enumerate(json.loads(Path(script).read_text(encoding="utf-8"))):
        result = doc.run(step["command"], step.get("params") or {})
        print(json.dumps({"step": i, "command": step["command"], "ok": True, "result": result}))
    return 0


TOOLS = [{"name": "run_command", "description": "Run one registry command.",
          "inputSchema": {"type": "object", "additionalProperties": False, "required": ["command"],
                          "properties": {"command": {"type": "string"}, "params": {"type": "object"}}}},
         {"name": "list_commands", "description": "List registry commands.",
          "inputSchema": {"type": "object", "properties": {}}}]


def mcp(app):
    doc = Doc(app)
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        method, p = msg["method"], msg.get("params") or {}
        if method == "initialize":
            out = {"protocolVersion": p.get("protocolVersion"), "capabilities": {"tools": {}},
                   "serverInfo": {"name": app}}
        elif method == "tools/list":
            out = {"tools": TOOLS}
        elif method == "tools/call" and p["name"] == "list_commands":
            out = {"content": [{"type": "text", "text": json.dumps(["shape.rectangle", "text.create"])}]}
        elif method == "tools/call":
            a = p.get("arguments") or {}
            try:
                got = doc.run(a["command"], a.get("params") or {})
                out = {"content": [{"type": "text", "text": json.dumps(got)}], "isError": False}
            except (ValueError, KeyError) as exc:
                out = {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True}
        else:
            out = {}
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": out}), flush=True)
    return 0


def main(argv):
    app, rest = argv[0], argv[1:]
    if rest[:1] == ["--version"]:
        print(f"{app}-cli {os.environ.get('FAKE_CRAFT_VERSION') or VERSIONS[app]}")
        return 0
    if rest[:1] == ["run"]:
        return run(app, rest[1:])
    if rest[:1] == ["mcp"]:
        return mcp(app)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
