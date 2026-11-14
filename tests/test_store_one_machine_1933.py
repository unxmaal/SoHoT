"""The shared store is reachable from its own machine only, which is what keeps one machine's facts unscoped. #1933 #1934"""
import yaml

from harness import store_service as svc

#: What a second machine's writes would break before they are scoped by machine.
UNSCOPED = ("proposals.state (one state from any machine's newest verdict, #1933); runtime_trials, engine_screens, "
            "engine_trials, gateway_switches, gateway_switch_runs, serve_waits, gateway_samples, gateway_requests, "
            "ledger_days (no machine_id, #1934)")


def test_every_published_store_port_is_loopback_until_per_machine_state_is_built():
    compose = yaml.safe_load(svc.COMPOSE.read_text(encoding="utf-8"))
    published = [p for s in compose["services"].values() for p in s.get("ports", [])]
    assert published
    for port in published:
        assert str(port).startswith("127.0.0.1:"), (
            f"{port} lets another machine write the store; first scope by machine: {UNSCOPED}")
