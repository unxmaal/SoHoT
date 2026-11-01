"""Staging cases judged from an open-vocabulary detector's boxes, and the checker's own controls (#1244)."""
import csv
import json
import os
from collections import Counter
from pathlib import Path

import pytest

from evals import core
from harness import reasons, staging_controls, staging_labels
from harness.checks import staging

ROOT = Path(__file__).resolve().parents[1]
IMAGE_CASES = ROOT / "evals" / "cases" / "image"
#: The machine's Hugging Face cache, read before the autouse fixture points HF_HOME at a tmp dir.
REAL_HF_HOME = os.environ.get("HF_HOME", "")


def _cases():
    """The hand-written staging cases; imported families live in subdirectories (#603)."""
    return [c for c in core.load_cases(IMAGE_CASES) if "staging" in c.assertions and c.source.parent == IMAGE_CASES]


def _box(label, x0, y0, x1, y1, score=0.9, **probes):
    return staging.Box(label, score, x0, y0, x1, y1, probes)


def test_box_level_controls_pass_without_the_detector():
    rows = staging_controls.run(detector=False)
    assert len(rows) == 19
    assert [r["scene"] for r in rows if not r["expected"]] == ["layout", "sizes", "attributes", "relations"]
    bad = [(r["scene"], r["expected"], r["failed"]) for r in rows if not r["ok"]]
    assert not bad


def test_every_requirement_of_every_reference_has_a_planted_break():
    refs = (("layout", staging_controls.LAYOUT), ("sizes", staging_controls.SIZES),
            ("attributes", staging_controls.ATTRIBUTES), ("relations", staging_controls.RELATIONS))
    broken = {(next(name for name, spec in refs if s.spec is spec), i)
              for s in staging_controls.scenes() for i in s.fails}
    wanted = {(name, i) for name, spec in refs for i in range(len(spec["require"]))}
    assert broken == wanted
    assert all(len(s.fails) <= 1 for s in staging_controls.scenes())


def test_the_controls_cover_every_requirement_type():
    kinds = {r["type"] for s in staging_controls.scenes() for r in s.spec["require"]}
    assert kinds == set(staging.TYPES)


def test_above_follows_genevals_margin():
    lamp, table = _box("lamp", 0.4, 0.1, 0.6, 0.3), _box("table", 0.3, 0.6, 0.7, 0.9)
    assert staging.above(lamp, table)
    assert not staging.above(table, lamp)
    level = _box("lamp", 0.4, 0.55, 0.6, 0.75)
    assert not staging.above(level, table)
    beside = _box("lamp", 0.0, 0.5, 0.1, 0.6)
    assert not staging.above(beside, _box("table", 0.8, 0.55, 0.9, 0.65))


def test_side_needs_every_instance_past_the_margin():
    spec = {"objects": {"cup": "a cup"}, "require": [{"type": "side", "object": "cup", "side": "left"}]}
    assert staging.evaluate(spec, [_box("cup", 0.1, 0.4, 0.3, 0.6)])[0].ok
    assert not staging.evaluate(spec, [_box("cup", 0.1, 0.4, 0.3, 0.6), _box("cup", 0.6, 0.4, 0.8, 0.6)])[0].ok
    centred = 0.5 - staging.SIDE_MARGIN / 2
    assert not staging.evaluate(spec, [_box("cup", centred - 0.1, 0.4, centred + 0.1, 0.6)])[0].ok


def test_bigger_needs_the_ratio_and_frame_reads_the_share():
    spec = {"objects": {"door": "a door", "man": "a man"},
            "require": [{"type": "bigger", "object": "door", "than": "man"},
                        {"type": "frame", "object": "door", "min": 0.4}]}
    big = _box("door", 0.1, 0.0, 0.8, 0.9)
    v = staging.evaluate(spec, [big, _box("man", 0.0, 0.5, 0.2, 0.9)])
    assert [x.ok for x in v] == [True, True]
    near = _box("man", 0.1, 0.0, 0.75, 0.9)
    v = staging.evaluate(spec, [big, near])
    assert [x.ok for x in v] == [False, True]
    v = staging.evaluate(spec, [_box("door", 0.1, 0.1, 0.5, 0.5), _box("man", 0.0, 0.8, 0.1, 0.9)])
    assert [x.ok for x in v] == [True, False]


def test_attribute_is_a_contrast_on_the_objects_own_box():
    spec = {"objects": {"door": "a door"},
            "require": [{"type": "attribute", "object": "door", "is": "an open door", "not": "a closed door"}]}
    assert staging.probes(spec) == ["an open door", "a closed door"]
    opened = _box("door", 0.2, 0.1, 0.6, 0.9, **{"an open door": 0.4, "a closed door": 0.2})
    shut = _box("door", 0.2, 0.1, 0.6, 0.9, score=0.95, **{"an open door": 0.1, "a closed door": 0.5})
    assert staging.evaluate(spec, [opened])[0].ok
    assert not staging.evaluate(spec, [opened, shut])[0].ok


def test_held_needs_the_object_inside_the_holder():
    spec = {"objects": {"key": "a key", "hand": "a hand"},
            "require": [{"type": "held", "object": "key", "by": "hand"}]}
    hand = _box("hand", 0.4, 0.4, 0.7, 0.7)
    assert staging.evaluate(spec, [hand, _box("key", 0.5, 0.5, 0.6, 0.6)])[0].ok
    assert not staging.evaluate(spec, [hand, _box("key", 0.1, 0.1, 0.2, 0.2)])[0].ok
    assert not staging.evaluate(spec, [_box("key", 0.5, 0.5, 0.6, 0.6)])[0].ok


def test_suppression_drops_a_box_over_two_instances_of_its_label():
    a, b = _box("cup", 0.1, 0.5, 0.3, 0.7, 0.8), _box("cup", 0.32, 0.5, 0.5, 0.7, 0.78)
    group = _box("cup", 0.1, 0.5, 0.5, 0.7, 0.4)
    assert staging.suppress([a, b, group]) == [a, b]
    assert len(staging.suppress([a, _box("plate", 0.1, 0.5, 0.3, 0.7, 0.5)])) == 2


def test_an_uncounted_type_is_reported_but_left_out_of_the_pass(tmp_path, monkeypatch):
    spec = {"objects": {"cup": "a cup"},
            "require": [{"type": "count", "object": "cup", "n": 1},
                        {"type": "side", "object": "cup", "side": "right"}]}
    v = staging.evaluate(spec, [_box("cup", 0.1, 0.4, 0.3, 0.6)], uncounted={"side"})
    assert [(x.ok, x.counted) for x in v] == [(True, True), (False, False)]
    image = tmp_path / "a.png"
    image.write_bytes(b"")
    monkeypatch.setattr(staging, "UNCOUNTED", frozenset({"side"}))
    monkeypatch.setattr(staging, "detect", lambda *a, **k: [_box("cup", 0.1, 0.4, 0.3, 0.6)])
    monkeypatch.setattr(staging, "device", lambda: "cpu")
    r = staging.check(image, spec)
    assert r.ok and r.metrics == {"staging": 1.0}
    side = json.loads(staging.sidecar(image).read_text(encoding="utf-8"))
    assert [x["counted"] for x in side["verdicts"]] == [True, False]
    assert side["detector"] == f"{staging.DETECTOR_REPO}@{staging.DETECTOR_REVISION}"


def test_a_staging_case_without_the_detector_is_a_harness_failure(tmp_path, monkeypatch):
    def missing(*a, **k):
        raise staging.DetectorUnavailable("No module named 'transformers'")
    monkeypatch.setattr(staging, "detect", missing)
    monkeypatch.setattr(staging, "device", lambda: "cpu")
    case = _cases()[0]
    from PIL import Image
    path = tmp_path / "out.png"
    Image.effect_noise((512, 512), 60).convert("RGB").save(path)
    r = core.CHECKERS["image"](path, case)
    assert not r.ok
    assert r.failure_class == reasons.MISSING_PACKAGE
    assert "staging not judged" in r.reason


def test_the_image_check_runs_staging_after_the_pixels(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(staging, "check", lambda path, spec, dev=None: calls.append(spec) or
                        core.CheckResult(True, "", metrics={"staging": 1.0}))
    case = _cases()[0]
    from PIL import Image
    blank = tmp_path / "blank.png"
    Image.new("RGB", (512, 512), (128, 128, 128)).save(blank)
    assert not core.CHECKERS["image"](blank, case).ok
    assert calls == []
    noisy = tmp_path / "noisy.png"
    Image.effect_noise((512, 512), 60).convert("RGB").save(noisy)
    r = core.CHECKERS["image"](noisy, case)
    assert r.ok and r.metrics["staging"] == 1.0
    assert calls == [case.assertions["staging"]]


@pytest.mark.parametrize("bad, why", [
    ({"objects": {}, "require": [{"type": "count", "object": "cup", "n": 1}]}, "objects"),
    ({"objects": {"cup": "a cup"}, "require": []}, "require"),
    ({"objects": {"cup": "a cup"}, "require": [{"type": "near", "object": "cup"}]}, "type"),
    ({"objects": {"cup": "a cup"}, "require": [{"type": "count", "object": "mug", "n": 1}]}, "not in objects"),
    ({"objects": {"cup": "a cup"}, "require": [{"type": "count", "object": "cup", "n": 1.5}]}, "whole number"),
    ({"objects": {"cup": "a cup"}, "require": [{"type": "side", "object": "cup", "side": "up"}]}, "left or right"),
    ({"objects": {"cup": "a cup"}, "require": [{"type": "above", "object": "cup", "over": "lamp"}]}, "over"),
    ({"objects": {"cup": "a cup"}, "require": [{"type": "frame", "object": "cup"}]}, "min or max"),
    ({"objects": {"cup": "a cup"}, "require": [{"type": "attribute", "object": "cup", "is": "a full cup"}]}, "is and not"),
    ({"objects": {"cup": "a cup"}, "require": [{"type": "count", "object": "cup", "n": 1, "colour": "red"}]}, "unknown"),
])
def test_a_malformed_staging_assertion_is_refused_at_load(tmp_path, bad, why):
    import yaml
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump({"id": "staging-bad", "modality": "image", "prompt": "p",
                                    "params": {"width": 512, "height": 512, "seed": 42},
                                    "assert": {"staging": bad}}), encoding="utf-8")
    with pytest.raises(ValueError, match=why):
        core.load_case(path)


def test_the_staging_checker_version_changes_the_cases_digest(monkeypatch):
    cases = _cases()
    before = core.cases_digest(cases)
    monkeypatch.setattr(staging, "CHECKER_VERSION", staging.CHECKER_VERSION + 1)
    bumped = core.cases_digest(cases)
    monkeypatch.undo()
    monkeypatch.setattr(staging, "UNCOUNTED", frozenset({"held"}))
    uncounted = core.cases_digest(cases)
    monkeypatch.undo()
    monkeypatch.setattr(staging, "DETECTOR_REVISION", "0" * 40)
    revised = core.cases_digest(cases)
    assert len({before, bumped, uncounted, revised}) == 4
    plain = [c for c in core.load_cases(IMAGE_CASES) if "staging" not in c.assertions]
    monkeypatch.undo()
    first = core.cases_digest(plain)
    monkeypatch.setattr(staging, "CHECKER_VERSION", 99)
    assert core.cases_digest(plain) == first


def test_the_staging_cases_spread_over_every_requirement_type():
    cases = _cases()
    assert 20 <= len(cases) <= 30
    per_type = Counter(t for c in cases for t in {r["type"] for r in c.assertions["staging"]["require"]})
    # left_of came with the GenEval import (#603), whose position rows cover it.
    assert set(per_type) == set(staging.TYPES) - {"left_of"}
    assert min(per_type.values()) >= 6, per_type
    assert all(c.params["width"] == c.params["height"] == 512 and isinstance(c.params["seed"], int) for c in cases)
    assert all(c.id.startswith("staging-") for c in cases)


def test_staging_reports_a_share_that_runs_higher():
    assert core.direction_of("staging") == "higher"


def _run_dir(tmp_path, n_images=8):
    rows = []
    spec = {"objects": {"cup": "a cup", "lamp": "a lamp"},
            "require": [{"type": "count", "object": "cup", "n": 2}, {"type": "above", "object": "lamp", "over": "cup"}]}
    for i in range(n_images):
        cand = "mflux/dev-q8" if i % 2 else "mflux/z-image-turbo-q8"
        image = tmp_path / f"{cand.replace('/', '_')}--staging-cups#{i}.png"
        image.write_bytes(b"png")
        verdicts = staging.evaluate(spec, [_box("cup", 0.1, 0.6, 0.2, 0.7), _box("cup", 0.3, 0.6, 0.4, 0.7)]
                                    + ([_box("lamp", 0.4, 0.1, 0.5, 0.2)] if i % 3 else []))
        staging.sidecar(image).write_text(json.dumps({"verdicts": [v.__dict__ for v in verdicts]}), encoding="utf-8")
        rows.append({"case_id": f"staging-cups#{i}", "candidate": cand, "artifact_path": str(image)})
    rows.append({"case_id": "fox-snow#1", "candidate": "mflux/dev-q8", "artifact_path": str(tmp_path / "fox.png")})
    (tmp_path / "results.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    return tmp_path


def test_the_labelling_sheet_hides_the_detector_verdicts(tmp_path):
    run = _run_dir(tmp_path)
    out = tmp_path / "sheet.csv"
    rows = staging_labels.sheet(run, n=6, out=out)
    assert len({r["image"] for r in rows}) == 6
    with out.open(encoding="utf-8") as f:
        written = list(csv.DictReader(f))
    assert set(written[0]) == {"item", "image", "requirement", "type", "question", "label"}
    assert all(r["label"] == "" for r in written)
    text = out.read_text(encoding="utf-8")
    assert "mflux" not in text and "staging-cups" not in text and "True" not in text
    assert all((out.parent / r["image"]).read_bytes() == b"png" for r in written)
    per_candidate = Counter(r["candidate"] for r in rows if r["requirement"] == 0)
    assert per_candidate["mflux/dev-q8"] == per_candidate["mflux/z-image-turbo-q8"] == 3
    again = staging_labels.sheet(run, n=6, out=tmp_path / "again.csv")
    assert [(r["source"], r["requirement"]) for r in again] == [(r["source"], r["requirement"]) for r in rows]


def test_agreement_reports_precision_and_recall_per_requirement_type(tmp_path):
    run = _run_dir(tmp_path)
    out = tmp_path / "sheet.csv"
    staging_labels.sheet(run, n=8, out=out)
    with out.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # The person sees every requirement met, so the detector's missing lamps are misses.
    for r in rows:
        r["label"] = "y"
    rows[0]["label"] = "?"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    table = {t["type"]: t for t in staging_labels.agreement(out, run)}
    assert set(table) == {"count", "above"}
    count, above = table["count"], table["above"]
    assert (count["n"], count["precision"], count["recall"]) == (7, 1.0, 1.0)
    assert count["counted"]
    assert (above["n"], above["precision"], above["recall"]) == (8, 1.0, 0.625)
    assert not above["counted"]
    assert above["recall_interval"][0] < above["recall"] < above["recall_interval"][1]


def test_agreement_refuses_an_unlabelled_sheet(tmp_path):
    run = _run_dir(tmp_path)
    out = tmp_path / "sheet.csv"
    staging_labels.sheet(run, n=4, out=out)
    with pytest.raises(ValueError, match="no labels"):
        staging_labels.agreement(out, run)


def test_the_night_command_pairs_the_four_candidates_over_three_seeds():
    argv = staging_labels.night()
    assert argv[:6] == ["uv", "run", "--group", "metrics", "python", "-m"]
    joined = " ".join(argv)
    assert "--modality image" in joined and "--repeat 3" in joined
    cands = argv[argv.index("--candidates") + 1].split(",")
    assert cands == ["mflux:dev", "mflux:z-image-turbo", "mflux:flux2-klein-4b", "mflux:z-image"]


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing", site="env:SOH_STAGING_DEVICE")
def test_the_device_seam_is_read_at_call_time_and_reaches_the_detector(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(staging, "detect", lambda path, objects, extra, dev: seen.append(dev) or [])
    spec = {"objects": {"cup": "a cup"}, "require": [{"type": "count", "object": "cup", "n": 0}]}
    image = tmp_path / "a.png"
    image.write_bytes(b"")
    for dev in staging.DEVICES:
        monkeypatch.setenv("SOH_STAGING_DEVICE", dev)
        assert staging.device() == dev
        assert staging.check(image, spec).ok
        assert json.loads(staging.sidecar(image).read_text(encoding="utf-8"))["device"] == dev
    assert seen == list(staging.DEVICES)
    monkeypatch.setenv("SOH_STAGING_DEVICE", "cuda")
    with pytest.raises(ValueError, match="SOH_STAGING_DEVICE"):
        staging.device()


def test_soh_staging_night_prints_the_queue_command(capsys):
    from harness import cli
    assert cli.main(["staging", "night"]) == 0
    out = capsys.readouterr().out
    assert "soh jobs --title 'staging #1244' add --night -- uv run --group metrics python -m evals.run" in out


def test_soh_staging_sheet_then_agreement_round_trips(tmp_path, capsys):
    from harness import cli
    (tmp_path / "run").mkdir()
    run = _run_dir(tmp_path / "run")
    sheet = tmp_path / "sheet.csv"
    assert cli.main(["staging", "sheet", str(run), "--out", str(sheet), "--n", "4"]) == 0
    assert cli.main(["staging", "agreement", str(sheet)]) == 1
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    for r in rows:
        r["label"] = "y"
    with sheet.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    capsys.readouterr()
    assert cli.main(["staging", "agreement", str(sheet)]) == 0
    out = capsys.readouterr().out
    assert "count" in out and "precision 1.00" in out


def _weights():
    if not REAL_HF_HOME:
        pytest.skip("no HF_HOME on this machine")
    pytest.importorskip("transformers", reason="needs the `metrics` dependency group")
    from huggingface_hub import try_to_load_from_cache
    hit = try_to_load_from_cache(staging.DETECTOR_REPO, "model.safetensors", cache_dir=str(Path(REAL_HF_HOME) / "hub"),
                                 revision=staging.DETECTOR_REVISION)
    if not isinstance(hit, str):
        pytest.skip(f"{staging.DETECTOR_REPO}@{staging.DETECTOR_REVISION[:8]} is not in the cache")


@pytest.fixture
def detector(monkeypatch):
    _weights()
    monkeypatch.setenv("HF_HOME", REAL_HF_HOME)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    staging._CACHE.clear()
    yield
    staging._CACHE.clear()


@pytest.mark.slow
def test_every_reference_composition_passes_through_the_detector(detector):
    rows = {r["scene"]: r for r in staging_controls.run("cpu")}
    for name in ("layout", "sizes", "attributes"):
        assert rows[name]["ok"] and rows[name]["failed"] == [], (name, rows[name]["details"])


@pytest.mark.slow
def test_each_planted_break_fails_exactly_its_requirement(detector):
    bad = [(r["scene"], r["expected"], r["failed"]) for r in staging_controls.run("cpu") if not r["ok"]]
    assert not bad


@pytest.mark.slow
def test_mps_verdicts_match_cpu_on_the_controls(detector):
    torch = pytest.importorskip("torch", reason="needs the `metrics` dependency group")
    if not torch.backends.mps.is_available():
        pytest.skip("no MPS here")
    cpu, mps = staging_controls.run("cpu"), staging_controls.run("mps")
    assert [r["failed"] for r in cpu] == [r["failed"] for r in mps]
    assert staging_controls.device_gap(cpu, mps) <= staging.DEVICE_BOX_TOLERANCE
