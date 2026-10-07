"""A stand-in for antirez/ds4's ds4-server: its flags, /v1/models and a streamed chat reply. #611."""
import http.server
import json
import os
import socketserver
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
args = sys.argv[1:]
i = 0
model = None
ctx = 0
host = "127.0.0.1"
port = 8000
chdir = None
streaming = False
cache_experts = None
while i < len(args):
    a = args[i]
    if a == "-m":
        model = args[i + 1]
        i += 2
    elif a == "--ctx":
        ctx = int(args[i + 1])
        i += 2
    elif a == "--host":
        host = args[i + 1]
        i += 2
    elif a == "--port":
        port = int(args[i + 1])
        i += 2
    elif a == "--chdir":
        chdir = args[i + 1]
        i += 2
    elif a == "--ssd-streaming":
        streaming = True
        i += 1
    elif a == "--ssd-streaming-cache-experts":
        cache_experts = args[i + 1]
        i += 2
    else:
        sys.stderr.write("ds4-server: unknown option " + a + "\n")
        sys.exit(2)
if chdir is not None:
    os.chdir(chdir)
if model is None or not os.path.exists(model):
    sys.stderr.write(f"ds4-server: cannot open model {model}\n")
    sys.exit(1)


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            obj = {"object": "list", "data": [{"id": "ds4-fake", "object": "model",
                                               "owned_by": "ds4.c", "context_length": ctx}]}
            self._send(200, "application/json", json.dumps(obj).encode("utf-8"))
        else:
            self._send(404, "text/plain", b"")

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send(404, "text/plain", b"")
            return
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n).decode("utf-8"))
        log = os.environ.get("DS4_FAKE_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for piece in ("def ", "f():", " pass"):
                chunk = {"choices": [{"index": 0, "delta": {"content": piece}}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode("utf-8"))
            usage = {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 3}}
            self.wfile.write(("data: " + json.dumps(usage) + "\n\n").encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            obj = {"choices": [{"index": 0, "message": {"role": "assistant",
                                                        "content": "def f(): pass"},
                                "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 3, "completion_tokens": 3}}
            self._send(200, "application/json", json.dumps(obj).encode("utf-8"))


class S(socketserver.TCPServer):
    allow_reuse_address = True


server = S((host, port), H)
print(f"ds4-server: listening on {host}:{port} streaming={streaming} "
      f"cache={cache_experts}", flush=True)
server.serve_forever()
