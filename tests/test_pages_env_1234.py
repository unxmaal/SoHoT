"""The Pages job renders the site with bare Python plus only what pages.yml installs, so the render is tried in exactly that environment. #1234."""
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
DATA = ROOT / "tests" / "fixtures" / "site"
NOW = 1_800_000_000.0


def _steps() -> list[dict]:
    return yaml.safe_load(PAGES.read_text(encoding="utf-8"))["jobs"]["build"]["steps"]


def installed() -> list[tuple[str, str]]:
    """(name, version) for each requirement a pip install step in pages.yml names, before Render."""
    out = []
    for step in _steps():
        if step.get("name") == "Render":
            return out
        words = (step.get("run") or "").split()
        if "pip" in words and "install" in words:
            for req in words[words.index("install") + 1:]:
                if not req.startswith("-"):
                    name, _, version = req.partition("==")
                    out.append((name.lower(), version))
    raise AssertionError("pages.yml has no Render step")


def _locked() -> dict[str, str]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    return {p["name"].lower(): p["version"] for p in lock["package"]}


def _site_packages(dest: Path) -> Path:
    """A directory holding only the distributions pages.yml installs, copied from this venv."""
    for name, version in installed():
        dist = importlib.metadata.distribution(name)
        assert dist.version == version, f"{name}: this venv has {dist.version}, pages.yml installs {version}"
        for f in dist.files or ():
            src = Path(dist.locate_file(f))
            if src.is_file():
                (dest / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest / f)
    return dest


def test_the_pages_render_of_a_pre_670_export_under_bare_python_with_pyyaml_matches_the_venv_render(tmp_path):
    from harness import publish, site
    machines = publish.load(DATA)
    rows = [r for m in machines for lane in m.get("lanes") or [] for r in lane.get("comparison") or []]
    assert rows and any("model" not in r for r in rows), "the fixture no longer holds a pre-#670 row"
    pkgs = _site_packages(tmp_path / "pkgs")
    code = ("import json, sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]\n"
            "from harness import publish, site\n"
            "assert publish.main(['render', '--data', sys.argv[3], '--out', sys.argv[4]]) == 0\n"
            "print(json.dumps(site.render(publish.load(sys.argv[3]), now=float(sys.argv[5]))))\n")
    got = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(ROOT), str(pkgs), str(DATA),
                          str(tmp_path / "site"), str(NOW)], capture_output=True, text=True, encoding="utf-8",
                         cwd=tmp_path, timeout=120)
    assert got.returncode == 0, got.stderr[-2000:]
    assert json.loads(got.stdout.splitlines()[-1]) == site.render(machines, now=NOW)
    assert (tmp_path / "site" / "reports" / "index.html").is_file()


def test_the_pages_workflow_installs_the_pyyaml_version_uv_lock_pins():
    got = dict(installed())
    assert got.get("pyyaml") == _locked()["pyyaml"], got
    assert all(v for v in got.values()), f"pages.yml installs an unpinned package: {got}"
