"""The smoke slot probe: a stream closed after its first token must free the llama-server slot (#1127)."""
import http.server
import json
import select
import socket
import threading
import time

import pytest

from harness import loopback, slot_probe


class Fake:
    """A gateway and router in one, streaming tokens; `frees` says whether a closed stream stops the generation."""

    def __init__(self, frees: bool, slots_shape: str = "is_processing", invisible: bool = False):
        self.frees, self.shape, self.busy, self.invisible = frees, slots_shape, False, invisible
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/slots"):
                    slot = ({"id": 0, "is_processing": fake.busy} if fake.shape == "is_processing"
                            else {"id": 0, "state": int(fake.busy)} if fake.shape == "state" else {"id": 0})
                    body = json.dumps([slot]).encode()
                else:
                    body = b"{}"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _gone(self) -> bool:
                """The client closed: its socket reads as EOF, whatever a write to it would say on this OS."""
                ready, _, _ = select.select([self.connection], [], [], 0)
                return bool(ready) and self.connection.recv(1, socket.MSG_PEEK) == b""

            def do_POST(self):
                asked = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.busy = not fake.invisible
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for _ in range(asked["max_tokens"]):
                        chunk = {"choices": [{"delta": {"content": "1\n"}}]}
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(0.01)
                        if self._gone():
                            raise ConnectionResetError
                except OSError:
                    if not fake.frees:
                        time.sleep(asked["max_tokens"] * 0.01)
                finally:
                    fake.busy = False

        self.server = loopback.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake():
    made = []

    def make(**kw):
        made.append(Fake(**kw))
        return made[-1]
    yield make
    for f in made:
        f.close()


def test_a_closed_stream_that_frees_its_slot_passes(fake):
    f = fake(frees=True)
    ok, line = slot_probe.probe(f.url, f.url, "tiny", max_tokens=2000, settle_s=3.0)
    assert ok, line
    assert "freed tiny's slot" in line


def test_a_slot_still_decoding_after_the_close_fails_and_names_the_fix(fake):
    f = fake(frees=False)
    ok, line = slot_probe.probe(f.url, f.url, "tiny", max_tokens=2000, settle_s=0.5)
    assert not ok
    assert "still decoding" in line and "router.upstream_for" in line


def test_older_slot_shapes_are_read_and_an_unknown_one_fails(fake):
    ok, _ = slot_probe.probe((f := fake(frees=True, slots_shape="state")).url, f.url, "tiny", max_tokens=2000, settle_s=3.0)
    assert ok
    ok, line = slot_probe.probe((g := fake(frees=True, slots_shape="none")).url, g.url, "tiny", max_tokens=2000)
    assert not ok and "--slots" in line


def test_the_probe_picks_the_smallest_loaded_model_no_running_job_names(tmp_path):
    small, big = tmp_path / "small.gguf", tmp_path / "big.gguf"
    small.write_bytes(b"x" * 10)
    big.write_bytes(b"x" * 1000)
    models = [{"id": "Ornith-1.5-35B-Q4_K_M", "status": {"value": "loaded", "args": ["-m", str(big)]}},
              {"id": "tiny", "status": {"value": "loaded", "args": ["-m", str(small)]}},
              {"id": "tinier", "status": {"value": "unloaded", "args": []}}]
    assert slot_probe.pick(models) == "tiny"
    busy = '["uv", "run", "python", "-m", "evals.run", "--candidates", "llamacpp:tiny"]'
    assert slot_probe.pick(models, busy) == "Ornith-1.5-35B-Q4_K_M"
    assert slot_probe.pick(models[:2], busy + " Ornith-1.5-35B-Q4_K_M") == ""


def test_idle_reads_each_slot():
    assert slot_probe.idle([{"is_processing": False}, {"is_processing": False}]) is True
    assert slot_probe.idle([{"is_processing": False}, {"is_processing": True}]) is False
    assert slot_probe.idle({"slots": [{"state": 0}]}) is True
    assert slot_probe.idle([]) is None


def test_a_slot_the_router_never_shows_busy_proves_nothing(fake):
    f = fake(frees=True, invisible=True)
    ok, line = slot_probe.probe(f.url, f.url, "tiny", max_tokens=2000, settle_s=1.0)
    assert not ok and "proves nothing" in line
