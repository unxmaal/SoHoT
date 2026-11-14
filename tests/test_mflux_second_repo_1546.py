"""An mflux family that loads a second repo has it fetched with the candidate, under the budget. #1546."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from harness import downloads, engines, fetching, reasons, screen, stages
from harness import memory_store as ms

GIB = fetching.GIB
FREE = 900 * GIB
LENS = "someone/Lens-Turbo"
ENCODER = "org/encoder-20b"
VAE = "org/vae-4b"
ROOT = Path(__file__).resolve().parent.parent

#: The tail of szwagros/Lens-Turbo's fox-snow stderr, verdicts 18260 and 18558.
LENS_STDERR = (
    "  File \"mflux/models/common/resolution/path_resolution.py\", line 84, in resolve\n"
    "huggingface_hub.errors.OfflineModeIsEnabled: Cannot reach "
    "https://huggingface.co/api/models/mlx-community/gpt-oss-20b-MXFP4-Q8/revision/main: offline mode is enabled.\n"
    "huggingface_hub.errors.LocalEntryNotFoundError: Cannot find an appropriate cached snapshot folder for the "
    "specified revision on the local disk and outgoing traffic has been disabled. To enable repo look-ups and "
    "downloads online, set 'HF_HUB_OFFLINE=0' as environment variable.\n")


def fake_mflux(root: Path) -> Path:
    """A uv tool tree laid out as mflux 0.19.1's: entry points, a Lens family with two repo constants, a flux family with none."""
    site = root / "lib" / "python3.12" / "site-packages"
    info = site / "mflux-9.9.9.dist-info"
    info.mkdir(parents=True)
    (info / "entry_points.txt").write_text(
        "[console_scripts]\n"
        "mflux-generate = mflux.models.flux.cli.flux_generate:main\n"
        "mflux-generate-lens = mflux.models.lens.cli.lens_generate:main\n", encoding="utf-8")
    files = {
        "mflux/models/lens/cli/lens_generate.py": "def main():\n    pass\n",
        "mflux/models/lens/model/text_encoder/enc.py": f'DEFAULT_ENCODER_REPO = "{ENCODER}"\n',
        "mflux/models/lens/variants/txt2img/img.py":
            f'VAE_REPO: str = "{VAE}"\nLORA_REPO_ID = "x/lora"\n'
            'def f():\n    INNER_REPO = "x/inner"\n',
        "mflux/models/flux/variants/loras.py": 'LORA_REPO_ID = "ali-vilab/In-Context-LoRA"\n',
        "mflux/models/common/pid.py": 'PID_REPO = "nvidia/PiD"\n',
    }
    for rel, text in files.items():
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        (site / rel).write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def tool(tmp_path, monkeypatch):
    root = fake_mflux(tmp_path / "uv-tools" / "mflux")
    monkeypatch.setattr(stages, "mflux_tool_root", lambda: root)
    return root


@pytest.fixture
def db(tmp_path, monkeypatch, tool):
    hf = tmp_path / "hf"
    (hf / "hub").mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(hf))
    conn = ms.connect()
    yield conn
    conn.close()


class Snapshot:
    def __init__(self):
        self.asked = []

    def __call__(self, repo_id, **kw):
        self.asked.append(repo_id)
        snap = downloads.hub_dir(repo_id) / "snapshots" / "abc"
        snap.mkdir(parents=True, exist_ok=True)
        for f in ("config.json", "model.safetensors"):
            (snap / f).write_bytes(b"x" * 100)
        import fakes
        fakes.hub_ref(snap)
        return str(snap)


def queued_lens(db, name=LENS, lane="image", tier="screen"):
    ms.record(db, ms.Seen(name=name, source="inspect", resolved=name, kind="weights", lane=lane))
    ms.decide(db, name, "queued", tier=tier)
    fetching.download(name, snapshot=Snapshot(), text=False, conn=db)
    assert fetching.have(name, db)


def state_of(db, name):
    return db.execute("SELECT v.outcome, v.reason, v.detail FROM proposals p "
                      "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone()


def test_the_repos_come_from_the_installed_family_module_constants(tool):
    assert engines.mflux_repos("mflux-generate-lens") == (ENCODER, VAE)
    assert engines.mflux_repos("mflux-generate") == ()
    assert engines.mflux_repos("mflux-generate-nothing") == ()
    assert engines.mflux_repos("mflux-generate-lens", tool.parent / "absent") == ()
    assert engines.mflux_needs(LENS) == (ENCODER, VAE)
    assert engines.mflux_needs("Qwen/Qwen3-4B") == ()


@pytest.mark.skipif(not list(stages.mflux_tool_root().glob("lib/python*/site-packages/mflux-*.dist-info")),
                    reason="mflux is not installed as a uv tool")
def test_the_installed_mflux_lens_loads_its_text_encoder_from_gpt_oss():
    got = engines.mflux_repos("mflux-generate-lens")
    assert "mlx-community/gpt-oss-20b-MXFP4-Q8" in got
    assert engines.mflux_needs("szwagros/Lens-Turbo") == got


def test_a_lens_candidate_requires_its_runners_repos(db):
    queued_lens(db)
    assert {ENCODER, VAE} <= set(fetching.requires(LENS, db))
    assert set(fetching.missing(LENS, db)) == {ENCODER, VAE}


def test_a_text_lane_name_that_reads_like_lens_needs_nothing_more(db):
    ms.record(db, ms.Seen(name="org/Lens-Turbo-chat", source="inspect", resolved="org/Lens-Turbo-chat",
                          kind="weights", lane="code"))
    assert fetching.requires("org/Lens-Turbo-chat", db) == []


def test_fetch_brings_the_second_repos_of_a_candidate_on_disk(db):
    queued_lens(db)
    snap = Snapshot()
    done = fetching.run(db, {ENCODER: 12 * GIB, VAE: 1 * GIB}, snapshot=snap, free=FREE)
    assert sorted(snap.asked) == [ENCODER, VAE]
    assert fetching.missing(LENS, db) == []
    assert all(d["ok"] for d in done if d["repo"] in (ENCODER, VAE))


def test_the_second_repos_count_against_the_download_budget(db):
    queued_lens(db)
    snap = Snapshot()
    done = fetching.run(db, {ENCODER: 12 * GIB, VAE: 2 * GIB}, snapshot=snap, free=FREE, budget=13 * GIB)
    assert snap.asked == [ENCODER]
    (vae,) = [d for d in done if d["repo"] == VAE]
    assert not vae["ok"] and "budget" in vae["why"]
    got = state_of(db, LENS)
    assert got["outcome"] == "queued" and got["reason"] == reasons.LIMIT and VAE in got["detail"]


def test_the_screen_waits_naming_the_missing_encoder(db):
    queued_lens(db)
    row = {"name": LENS, "lane": "image", "attaches_to": ""}
    (got,) = screen.plan([row], missing=lambda m: fetching.missing(m, db))
    assert got["state"] == screen.WAITING and ENCODER in got["why_not"]


def test_an_offline_miss_names_the_repo_the_runner_looked_for(tmp_path):
    from evals.core import load_cases
    from evals.runners.base import RunnerError
    from evals.runners.process import ProcessRunner
    assert reasons.offline_repo(LENS_STDERR) == "mlx-community/gpt-oss-20b-MXFP4-Q8"
    assert reasons.offline_repo("LocalEntryNotFoundError: no network") == ""
    fake = tmp_path / "lens.py"
    fake.write_text(f"import sys\nsys.stderr.write({LENS_STDERR!r})\nsys.exit(1)\n", encoding="utf-8")
    eng = dataclasses.replace(engines.resolve(f"mflux:{LENS}"), argv=lambda p, o, params: [sys.executable, str(fake)])
    case = next(c for c in load_cases(ROOT / "evals" / "cases" / "image") if c.id == "fox-snow")
    with pytest.raises(RunnerError) as got:
        ProcessRunner(eng, tmp_path / "out").generate(case)
    detail = str(got.value)
    assert "needs mlx-community/gpt-oss-20b-MXFP4-Q8, which is not in the hub cache" in detail
    assert reasons.classify(detail) == reasons.HARNESS_ERROR
