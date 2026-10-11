"""A node-served run is filed under the node's machine row; a node with no fingerprint fails loudly. #781."""
import importlib.util
from pathlib import Path

import pytest
import yaml

from evals import run as R
from evals.core import Receipt, comparable
from harness import gateway, machine, nodes, runs
from harness import memory_store as ms

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("served_model_781", REPO / "gateway" / "served_model.py")
served = importlib.util.module_from_spec(spec)
spec.loader.exec_module(served)

HW = "AMD64 Family 26 Model 68 Stepping 0, AuthenticAMD"
KHRYLL = f"{HW}/Windows/AMD64/37b7b3682e08"
HERE = "Mac17,15/macOS/arm64/b82b652fe135"
BASE = """model_list:
  - model_name: Qwen2.5-7B-Instruct-Q4_K_M
    engine: llama-server
    litellm_params:
      model: openai/Qwen2.5-7B-Instruct-Q4_K_M
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
"""
MODEL = "Qwen2.5-7B-Instruct-Q4_K_M"


def windows(build: int) -> str:
    """platform.platform() on Windows: the build is the part that changes monthly."""
    return f"Windows-10-10.0.{build}-SP0"


def node(**kw):
    raw = {"name": "khryll", "api_base": "http://node.invalid:18082/v1", "engine": "llama-server",
           "models": [MODEL]}
    raw.update(kw)
    return nodes.parse({"nodes": [raw]})


def header(tmp_path, monkeypatch, nodes_list):
    """The x-sohot-machine a node-served reply carries."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    gateway.write_served(cfg, defaults={}, nodes=nodes_list)
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    return served.serving_machine(MODEL)


def filed(conn, tmp_path, who, name="r.json"):
    """The machine_id a run is stored under when one gateway reply named `who`."""
    seen = {("http://127.0.0.1:4000", MODEL): {"machine": who, "machines": [who]}}
    serving, away = R.serving_machine(seen, HERE)
    client = {"hw_model": "Mac17,15", "os": "macOS-27.0.1-arm64-arm-64bit", "arch": "arm64",
              "host": "b82b652fe135"}
    payload = {"environment": R.serving_environment(client, serving, away),
               "receipt": {"modality": "code", "machine": serving},
               "rows": [{"case_id": "c", "passed": True}]}
    run_id = runs.record(conn, tmp_path / name, payload, at=1.0)
    return conn.execute("SELECT machine_id FROM runs WHERE id = ?", (run_id,)).fetchone()["machine_id"]


def _row(conn, mid):
    return dict(conn.execute("SELECT * FROM machines WHERE id = ?", (mid,)).fetchone())


def test_a_board_name_with_a_slash_still_files_under_its_row(tmp_path, monkeypatch):
    conn = ms.connect(tmp_path / "s.db")
    fp = "B550/X570 Board/Linux/x86_64/abcdefabcdef"
    mid = filed(conn, tmp_path, header(tmp_path, monkeypatch, node(machine=fp)))
    assert mid is not None and _row(conn, mid)["hw_model"] == "B550/X570 Board"
    conn.close()


def test_a_windows_build_bump_keeps_one_identity_and_one_machine_row(tmp_path, monkeypatch):
    """A Windows build number changes monthly; the node's identity must not change with it."""
    before = node(machine=f"{HW}/{windows(26100)}/AMD64/37b7b3682e08")
    after = node(machine=f"{HW}/{windows(26200)}/AMD64/37b7b3682e08")
    assert before[0].identity == after[0].identity == KHRYLL
    conn = ms.connect(tmp_path / "s.db")
    one = filed(conn, tmp_path, header(tmp_path, monkeypatch, before), "a.json")
    two = filed(conn, tmp_path, header(tmp_path, monkeypatch, after), "b.json")
    assert one == two and one is not None
    assert conn.execute("SELECT COUNT(*) FROM machines WHERE arch = 'AMD64'").fetchone()[0] == 1
    got = _row(conn, one)
    assert (got["fingerprint"], got["hw_model"], got["arch"]) == (KHRYLL, HW, "AMD64")
    assert machine.os_family(got["os"]) == "Windows"
    base = dict(modality="code", case_ids=("a",), repeat=1, sampling={}, gateway="g")
    ok, why = comparable(Receipt(**base, machine=before[0].identity),
                         Receipt(**base, machine=after[0].identity))
    assert ok, why
    conn.close()


def test_a_reply_from_a_node_with_no_fingerprint_warns_naming_the_node_and_key(capsys, monkeypatch):
    monkeypatch.setattr(nodes, "path", lambda environ=None: Path("~/lh/nodes.yaml"))
    R.warn_unfiled("node:khryll")
    err = capsys.readouterr().err
    assert "khryll" in err and "machine:" in err and "~/lh/nodes.yaml" in err


@pytest.mark.parametrize("who", ["unknown: http://g did not name its machine", "upstream:h:1"])
def test_a_run_from_an_unknown_host_warns(capsys, who):
    R.warn_unfiled(who)
    assert "no machine" in capsys.readouterr().err


def test_a_run_from_a_fingerprinted_host_does_not_warn(capsys):
    R.warn_unfiled(KHRYLL)
    assert capsys.readouterr().err == ""


class Reply:
    status_code = 200

    def __init__(self, h):
        self.headers = h


def test_smoke_fails_a_node_with_no_machine_fingerprint():
    got = nodes.smoke("g", "k", node(), get=lambda url, n: (200, {MODEL}),
                      ask=lambda *a: Reply({"x-sohot-node": "khryll", "x-sohot-machine": "node:khryll"}))
    bad = [line for ok, line in got if not ok]
    assert bad and "khryll" in bad[0] and "machine:" in bad[0]


def test_smoke_fails_a_gateway_that_names_another_machine_for_the_node():
    """A gateway still serving a config from before `machine:` was set files runs as node:<name>."""
    got = nodes.smoke("g", "k", node(machine=KHRYLL), get=lambda url, n: (200, {MODEL}),
                      ask=lambda *a: Reply({"x-sohot-node": "khryll", "x-sohot-machine": "node:khryll"}))
    assert not got[0][0] and "node:khryll" in got[0][1]
    ok = nodes.smoke("g", "k", node(machine=KHRYLL), get=lambda url, n: (200, {MODEL}),
                     ask=lambda *a: Reply({"x-sohot-node": "khryll", "x-sohot-machine": KHRYLL}))
    assert all(p for p, _ in ok), ok


def test_the_node_check_fails_a_node_with_no_machine_and_passes_one_with(tmp_path, monkeypatch, capsys):
    f = tmp_path / "nodes.yaml"
    raw = {"name": "khryll", "api_base": "http://h.invalid:1/v1", "engine": "llama-server",
           "models": [MODEL]}
    f.write_text(yaml.safe_dump({"nodes": [raw]}), encoding="utf-8")
    monkeypatch.setenv(nodes.ENV_VAR, str(f))
    assert nodes.main(["check"]) == 1
    assert "khryll" in capsys.readouterr().out
    f.write_text(yaml.safe_dump({"nodes": [{**raw, "machine": "PC/Windows"}]}), encoding="utf-8")
    assert nodes.main(["check"]) == 1
    f.write_text(yaml.safe_dump({"nodes": [{**raw, "machine": KHRYLL}]}), encoding="utf-8")
    assert nodes.main(["check"]) == 0


def test_launchd_install_fails_on_the_node_check():
    gen = (REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    body = gen.split("install_units() {", 1)[1].split("\n}\n", 1)[0]
    assert "harness.nodes check" in body
    assert body.index("harness.nodes check") > body.index("launchctl bootstrap")
