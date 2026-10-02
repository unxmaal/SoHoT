"""The page a person labels an eval set on. Issue #286.

One item at a time, one button per label in the rubric plus can't-tell. A
repeat is shown exactly like a fresh item, so it measures judgment rather than
memory. Stdlib only, like judge_server.
"""
from __future__ import annotations

import html
import random
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from harness import rubric_eval as rv

PAGE = """<!doctype html><meta charset=utf-8>
<title>{name} &middot; label</title>
<style>
 body{{font:16px/1.5 system-ui,sans-serif;margin:0;padding:2rem;
   background:#14161a;color:#e8e8ea}}
 .q{{color:#8b90a0;max-width:860px;margin-bottom:1rem}}
 .sub{{color:#8b90a0;font-size:.85rem;margin-bottom:1rem}}
 pre{{white-space:pre-wrap;background:#1c1f26;border:1px solid #2a2e38;
   border-radius:8px;padding:1rem;max-width:860px;font:15px/1.5 ui-monospace,monospace}}
 form{{display:flex;gap:.75rem;max-width:860px;margin-top:1.25rem;flex-wrap:wrap}}
 button{{flex:1;padding:.85rem;font:inherit;border-radius:6px;cursor:pointer;
   border:1px solid #2a2e38;background:#232733;color:#e8e8ea}}
 button:hover{{background:#2d3240}}
 .ct{{flex:0 0 11rem;color:#8b90a0}}
</style>
<div class=q>{question}</div>
<div class=sub>{progress}</div>
{body}
"""


class Labeller(BaseHTTPRequestHandler):
    root: Path = Path()
    rng = random.Random(0)
    repeat_rate = 0.2

    def log_message(self, *a):
        pass

    def _send(self, body: str, code: int = 200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlparse(self.path).path not in ("/", "/index.html"):
            return self._send("no", 404)
        s = rv.load_set(self.root)
        done = len(rv.labels(self.root))
        progress = f"{done} of {len(s.items)} labelled"
        nxt = rv.next_item(self.root, self.rng, self.repeat_rate)
        if nxt is None:
            body = "<p>Nothing left to label.</p>"
        else:
            item, _ = nxt
            buttons = "".join(
                f'<button name=label value="{html.escape(v)}">{html.escape(v)}</button>'
                for v in s.rubric.labels)
            body = (f"<pre>{html.escape(item['text'])}</pre>"
                    f'<form method=post action="/label">'
                    f'<input type=hidden name=id value="{html.escape(item["id"])}">'
                    f"{buttons}"
                    f'<button class=ct name=label value="{rv.CANT_TELL}">'
                    f"Can&rsquo;t tell</button></form>")
        self._send(PAGE.format(name=html.escape(s.rubric.name),
                               question=html.escape(s.rubric.instructions),
                               progress=progress, body=body))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(n).decode("utf-8"))
        get = lambda k: (form.get(k) or [""])[0]
        try:
            item_id = get("id")
            rv.record_label(self.root, item_id, get("label"),
                            repeat=item_id in rv.labels(self.root))
        except (KeyError, ValueError) as exc:
            return self._send(html.escape(str(exc)), 400)
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


def make(root, port: int = 8766, repeat_rate: float = 0.2,
         seed: int | None = None) -> HTTPServer:
    rv.load_set(root)
    handler = type("Bound", (Labeller,), {
        "root": Path(root), "repeat_rate": repeat_rate,
        "rng": random.Random(seed)})
    return HTTPServer(("127.0.0.1", port), handler)


def serve(root, port: int = 8766, repeat_rate: float = 0.2,
          open_browser: bool = True) -> None:
    srv = make(root, port, repeat_rate)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"labelling {root}\n  {url}\n  ctrl-c when done; labels save as you go")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.server_close()
