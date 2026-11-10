"""Limits of the Docker engine the untrusted, non-GPU steps run on (#1510)."""
from harness.knobs.base import _k

C = "harness/containers.py"

KNOBS = [
    _k("docker_info_timeout_s", [f"{C}:INFO_TIMEOUT_S"], [5.0, 10.0, 30.0], unit="s",
       note="seconds `docker info` may take; past it Docker counts as down, its VM as 0 GiB and trial installs wait (#1510)"),
]

NOT_GATING = {
    f"{C}:VM_TTL_S": "seconds a Docker VM size read is reused; the VM's size changes only when its owner resizes it (#1510)",
}
