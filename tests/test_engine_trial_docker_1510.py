"""Engine trials download in a Docker container; only wheels verified against their published sha256 install natively. #1510."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from harness import admission, containers, memory
from harness import engine_trials as et
from tests.test_engine_trials_1475 import (EVIDENCE, FAKE_ENGINE, FakeGh, _readings, _tool, conn)  # noqa: F401

PLATFORM = "macosx_15_0_arm64"
OWN = "fast_serve-1.4.2-py3-none-any.whl"
DEP = "tiny_dep-0.1-cp312-cp312-macosx_14_0_arm64.whl"


def _trial(channel=et.PYPI, package="fast-serve", version="1.4.2"):
    return et.Trial(id=1, name=FAKE_ENGINE, kind="engine", state=et.CLASSIFIED, channel=channel, package=package,
                    version=version)


def _plant(wheels: Path, files: dict) -> dict:
    """Wheels named as given; returns the index the fake digest reads, filename -> sha256."""
    wheels.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (wheels / name).write_bytes(data)
    return {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}


def _index(published: dict):
    return lambda t, filename, name, version: published.get(filename, "")


class Machine:
    """Plays docker (the container leaves `files` in its /out mount) and uv; records each argv."""

    def __init__(self, files: dict):
        self.files, self.calls = files, []

    def __call__(self, argv, env, cwd, timeout=None):
        self.calls.append(argv)
        if argv[1:2] == ["run"]:
            out = Path(next(a for a in argv if a.endswith(":/out:rw")).rsplit(":", 2)[0])
            for name, data in self.files.items():
                (out / name).write_bytes(data)
        elif "venv" in argv and "pip" not in argv:
            Path(argv[-1], "bin").mkdir(parents=True, exist_ok=True)

    def native(self):
        return [a for a in self.calls if a[1:2] != ["run"]]


# ---- the split: download in the container, nothing of this machine in it ------------------

def test_the_download_runs_in_a_locked_down_container_that_shares_only_the_wheels_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(et.IMAGE_ENV, "registry.example.org/pip:9")
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    name, argv = et.fetch_argv(_trial(), wheels, PLATFORM)
    assert argv[1:3] == ["run", "--rm"] and argv[argv.index("--name") + 1] == name
    for flag in ("--read-only", "--cap-drop", "no-new-privileges", "--pids-limit", "--memory", "--cpus"):
        assert flag in argv
    assert argv[argv.index("--user") + 1] == "65534:65534"
    assert argv[argv.index("--memory") + 1] == f"{int(et.CONTAINER_MEMORY_GB * 1024)}m"
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert mounts == [f"{wheels.resolve()}:/out:rw"]
    envs = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert all(e.split("=")[0] in ("HOME", "PIP_CACHE_DIR", "PIP_DISABLE_PIP_VERSION_CHECK", "PIP_NO_INPUT")
               for e in envs)
    image = argv.index("registry.example.org/pip:9")
    assert argv[image + 1:image + 4] == ["python", "-I", "-c"] and "fast-serve==1.4.2" in argv
    assert argv[argv.index("--platform") + 1] == PLATFORM and "--only-binary=:all:" in argv
    assert str(Path.home()) not in " ".join(a for a in argv if not a.startswith(str(wheels.resolve())))


def test_a_release_asset_that_is_no_wheel_name_never_reaches_the_container(tmp_path):
    with pytest.raises(et.TrialError, match="no wheel file name"):
        et.fetch_argv(_trial(et.RELEASE, "x.whl; rm -rf /", "v1"), tmp_path, PLATFORM)
    name, argv = et.fetch_argv(_trial(et.RELEASE, OWN, "v1.4.2"), tmp_path, PLATFORM)
    assert f"https://github.com/{FAKE_ENGINE}/releases/download/v1.4.2/{OWN}" in argv


def test_the_platform_is_this_macs_read_at_call_time():
    assert et.target_platform(lambda: ("27.2", ("", "", ""), ""), lambda: "arm64") == "macosx_27_0_arm64"
    with pytest.raises(et.TrialError, match="no macOS version"):
        et.target_platform(lambda: ("", ("", "", ""), ""), lambda: "x86_64")


# ---- verify: what runs natively is only what its index published --------------------------

def test_verified_wheels_become_hash_pinned_requirements(tmp_path):
    published = _plant(tmp_path, {OWN: b"own", DEP: b"dep"})
    lines = et.verify(_trial(), tmp_path, PLATFORM, _index(published))
    assert lines == [f"fast-serve==1.4.2 --hash=sha256:{published[OWN]}",
                     f"tiny-dep==0.1 --hash=sha256:{published[DEP]}"]


@pytest.mark.parametrize("files,published,why", [
    ({OWN: b"own", DEP: b"tampered"}, {OWN: b"own", DEP: b"dep"}, "is not the published"),
    ({OWN: b"own", DEP: b"dep"}, {OWN: b"own"}, "publishes no sha256"),
    ({OWN: b"own", "setup.py": b"x"}, {OWN: b"own"}, "which is no wheel"),
    ({OWN: b"own", "dep-1.0-cp312-cp312-manylinux_2_17_aarch64.whl": b"d"},
     {OWN: b"own", "dep-1.0-cp312-cp312-manylinux_2_17_aarch64.whl": b"d"}, "does not run on"),
    ({DEP: b"dep"}, {DEP: b"dep"}, "did not fetch fast-serve 1.4.2"),
    ({"fast_serve-1.4.1-py3-none-any.whl": b"o"}, {"fast_serve-1.4.1-py3-none-any.whl": b"o"}, "did not fetch"),
    ({}, {}, "fetched nothing"),
])
def test_anything_unverified_blocks_the_trial(tmp_path, files, published, why):
    _plant(tmp_path, files)
    index = {n: hashlib.sha256(d).hexdigest() for n, d in published.items()}
    with pytest.raises(et.TrialError, match=why):
        et.verify(_trial(), tmp_path, PLATFORM, _index(index))


def test_a_symlink_the_container_left_is_refused(tmp_path):
    published = _plant(tmp_path, {OWN: b"own"})
    (tmp_path / DEP).symlink_to(tmp_path / OWN)
    with pytest.raises(et.TrialError, match="which is no wheel"):
        et.verify(_trial(), tmp_path, PLATFORM, _index({**published, DEP: published[OWN]}))


def test_the_index_digest_is_pypis_for_a_dependency_and_githubs_for_the_release_wheel(monkeypatch):
    asked = []
    monkeypatch.setattr(et, "_pypi_json", lambda p: asked.append(p) or {"urls": [
        {"filename": DEP, "digests": {"sha256": "aa" * 32}}]})
    assert et.index_digest(_trial(), DEP, "tiny-dep", "0.1") == "aa" * 32 and asked == ["tiny-dep/0.1"]
    assert et.index_digest(_trial(), "other.whl", "other", "1") == ""
    rel = {"assets": [{"name": OWN, "digest": "sha256:" + "bb" * 32}, {"name": "x.whl"}]}
    monkeypatch.setattr(et, "_gh_json", lambda client, path: rel if path.endswith("/releases/tags/v1") else None)
    t = _trial(et.RELEASE, OWN, "v1")
    assert et.index_digest(t, OWN, "fast-serve", "1.4.2", client=object()) == "bb" * 32
    rel["assets"][0].pop("digest")
    assert et.index_digest(t, OWN, "fast-serve", "1.4.2", client=object()) == ""


# ---- install: container, verify, then the offline native install ---------------------------

def test_install_fetches_in_the_container_verifies_then_installs_offline_under_the_sandbox(tmp_path):
    files = {OWN: b"own", DEP: b"dep"}
    machine = Machine(files)
    d = et.install(_trial(), tmp_path, run=machine, digest=_index(_plant(tmp_path / "index", files)), plat=PLATFORM)
    assert machine.calls[0][1] == "run"
    venv, pip = machine.native()
    assert venv[0] == pip[0] == et.SANDBOX_EXEC
    profile = Path(pip[2])
    assert profile.name == "offline.sb" and "(deny network*)" in profile.read_text(encoding="utf-8")
    for flag in ("--offline", "--no-index", "--require-hashes"):
        assert flag in pip
    assert pip[pip.index("--find-links") + 1] == str((d / "wheels").resolve())
    assert (d / "installed.json").is_file()


def test_a_tampered_wheel_runs_nothing_natively_and_leaves_no_installed_marker(tmp_path):
    machine = Machine({OWN: b"own", DEP: b"tampered"})
    published = _plant(tmp_path / "index", {OWN: b"own", DEP: b"dep"})
    with pytest.raises(et.TrialError, match="is not the published"):
        et.install(_trial(), tmp_path, run=machine, digest=_index(published), plat=PLATFORM)
    assert machine.native() == []
    assert not list(tmp_path.glob("*/installed.json"))


def test_wheels_an_interrupted_fetch_left_are_fetched_again_not_trusted(tmp_path):
    stale = tmp_path / "fakeorg-fast-serve-1-4-2" / "wheels"
    stale.mkdir(parents=True)
    (stale / "evil-1.0-py3-none-any.whl").write_bytes(b"evil")
    files = {OWN: b"own"}
    machine = Machine(files)
    et.install(_trial(), tmp_path, run=machine, digest=_index(_plant(tmp_path / "index", files)), plat=PLATFORM)
    assert sorted(p.name for p in stale.iterdir()) == [OWN]


def test_a_failed_download_removes_its_container_and_an_oom_kill_is_a_cut(tmp_path, monkeypatch):
    removed, cut = [], []
    monkeypatch.setattr(containers, "remove", lambda name, run=None: removed.append(name))
    from harness import cuts
    monkeypatch.setattr(cuts, "cut", lambda knob, *a, **k: cut.append(knob))

    def killed(argv, env, cwd, timeout=None):
        raise et.TrialError("install exited 137: Killed", 137)
    with pytest.raises(et.TrialError, match="137"):
        et.install(_trial(), tmp_path, run=killed, digest=_index({}), plat=PLATFORM)
    assert removed and removed[0].startswith("sohot-trial-") and cut == ["engine_trial_container_memory_gb"]


def test_classified_trials_wait_for_docker_rather_than_install_without_it(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(et, "can_sandbox", lambda: True)
    monkeypatch.setattr(et, "docker_here", lambda: False)
    installs = []
    got = et.sweep(conn, [_tool(conn, FAKE_ENGINE)], [], ask=_readings(), evidence=EVIDENCE.__getitem__,
                   installer=lambda t, root: installs.append(t), gh=FakeGh(), root=tmp_path, now=5000.0)
    (t,) = et.trials(conn)
    assert installs == [] and t.state == et.CLASSIFIED and "Docker" in got.stopped


# ---- the Docker VM is counted in the memory budget -----------------------------------------

def _info(stdout, rc=0):
    return lambda argv, **kw: subprocess.CompletedProcess(argv, rc, stdout, "")


def test_the_vm_size_is_read_from_docker_and_zero_when_docker_is_absent_or_down(monkeypatch):
    monkeypatch.setattr(containers, "_info", containers._info.real)
    monkeypatch.setattr(containers, "docker", lambda: "/usr/local/bin/docker")
    assert containers.vm_gb(run=_info("8589934592 10\n")) == 8.0
    assert containers.vm_gb(run=_info("", rc=1)) == 0.0
    assert containers.vm_gb(run=_info("8589934592 10\n", rc=1)) == 0.0
    assert containers.vm_gb(run=_info("Cannot connect to the Docker daemon\n")) == 0.0
    monkeypatch.setattr(containers, "docker", lambda: "")
    assert containers.vm_gb(run=_info("8589934592 10\n")) == 0.0 and not containers.available()


def test_the_vm_size_is_reused_within_its_ttl(monkeypatch):
    asked = []
    monkeypatch.setattr(containers, "_info", lambda run=None: asked.append(1) or {"mem_bytes": 4 * 1024 ** 3, "cpus": 2})
    assert containers.vm_gb(now=100.0) == 4.0 and containers.vm_gb(now=100.0 + containers.VM_TTL_S - 1) == 4.0
    assert len(asked) == 1
    containers.vm_gb(now=100.0 + containers.VM_TTL_S + 1)
    assert len(asked) == 2


def test_the_vm_comes_off_the_ceiling_in_check_model_room_and_admission(monkeypatch):
    monkeypatch.setattr(containers, "vm_gb", lambda run=None, now=None: 8.0)
    monkeypatch.setattr(memory, "available_gb", lambda: 100.0)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 60.0)
    monkeypatch.setattr(memory, "pinned_gb", lambda: 10.0)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda conn=None: 5.0)
    monkeypatch.setattr(memory, "need_gb", lambda *a, **k: 40.0)
    ok, why = memory.check_model("org/mlx-big", reserve_gb=5.0)
    assert not ok and "8.0 GB given to the Docker VM" in why and "37.0 GB is safely available" in why
    assert memory.room_gb() == 37.0 and memory.held_gb() == 18.0
    room, how = admission.budget_gb([])
    assert room == 37.0 and "18.0 GiB held" in how


def test_vm_free_memory_is_not_counted_twice_when_available_is_the_bound(monkeypatch):
    monkeypatch.setattr(containers, "vm_gb", lambda run=None, now=None: 8.0)
    monkeypatch.setattr(memory, "available_gb", lambda: 20.0)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 60.0)
    monkeypatch.setattr(memory, "pinned_gb", lambda: 0.0)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda conn=None: 5.0)
    assert memory.room_gb() == 15.0


# ---- the real container, where Docker answers ---------------------------------------------

def _docker_image() -> str:
    exe = shutil.which("docker")
    if not exe or not containers._info():
        return ""
    image = et.IMAGE
    got = subprocess.run([exe, "image", "inspect", image], capture_output=True, timeout=30)
    return image if got.returncode == 0 else ""


@pytest.mark.skipif(not _docker_image(), reason=f"needs a docker engine with {et.IMAGE} already pulled")
def test_the_real_container_fetches_mac_wheels_offline_and_they_verify(tmp_path):
    src, wheels = tmp_path / "src", tmp_path / "wheels"
    published = {}
    for name, tag in ((OWN, "py3-none-any"), (DEP, "cp312-cp312-macosx_14_0_arm64")):
        published.update(_plant(src, {name: _wheel(name, tag)}))
    wheels.mkdir()
    pip = ["--only-binary=:all:", "--platform", PLATFORM, "--python-version", et.PYTHON, "--implementation", "cp",
           "--no-index", "--find-links", "/in"]
    argv = containers.run_argv(et.IMAGE, ["python", "-I", "-c", et.FETCH, "", "fast-serve==1.4.2", *pip],
                               name=f"sohot-test-1510-{tmp_path.name[-12:]}",
                               mounts=[(wheels.resolve(), "/out", "rw"), (src.resolve(), "/in", "ro")],
                               memory_gb=et.CONTAINER_MEMORY_GB, cpus=1, network=False)
    got = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    assert got.returncode == 0, got.stderr[-800:]
    lines = et.verify(_trial(), wheels, PLATFORM, _index(published))
    assert [ln.split()[0] for ln in lines] == ["fast-serve==1.4.2", "tiny-dep==0.1"]


def _wheel(filename: str, tag: str) -> bytes:
    """A minimal valid wheel; fast-serve depends on tiny-dep, so pip must resolve one for the target Mac."""
    import base64
    import io
    import zipfile
    dist, version = filename.split("-")[:2]
    info = f"{dist}-{version}.dist-info"
    requires = "Requires-Dist: tiny-dep==0.1\n" if dist == "fast_serve" else ""
    files = {f"{dist}/__init__.py": b"",
             f"{info}/METADATA": f"Metadata-Version: 2.1\nName: {dist.replace('_', '-')}\nVersion: {version}\n"
                                 f"{requires}".encode(),
             f"{info}/WHEEL": f"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: {tag}\n".encode()}
    record = [f"{k},sha256={base64.urlsafe_b64encode(hashlib.sha256(v).digest()).rstrip(b'=').decode()},{len(v)}"
              for k, v in files.items()] + [f"{info}/RECORD,,"]
    files[f"{info}/RECORD"] = ("\n".join(record) + "\n").encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()
