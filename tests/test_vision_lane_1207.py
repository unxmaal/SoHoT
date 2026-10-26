"""The vision lane: shot scale of film frames against CineScale's human labels, gated by a shuffled-label control. #1207."""
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from evals import vision
from harness import lanes, paths, privacy, publish
from harness.checks import shot_scale as ss

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "evals" / "cases" / "vision"
L = ss.LADDER


def rows(truth, answers, film="a"):
    return [{"film": film, "id": f"{film}-{i}", "truth": t, "answer": a}
            for i, (t, a) in enumerate(zip(truth, answers))]


def mixed(n=700, seed=0, films=("a", "b")):
    rng = random.Random(seed)
    out = []
    for f in films:
        out += rows([rng.choice(L) for _ in range(n)], [""] * n, film=f)
    return out


# --- the lane ----------------------------------------------------------------

def test_vision_is_a_by_hand_lane_discovery_never_searches_for():
    assert "vision" in lanes.BY_HAND and "vision" not in lanes.ALL


# --- the checker ---------------------------------------------------------------

@pytest.mark.parametrize("reply,label", [
    ("MCU", "MCU"), ("  ms ", "MS"), ("Answer: ELS.", "ELS"), ("CU", "CU"),
    ("medium close-up", "MCU"), ("Extreme long shot", "ELS"), ("close up", "CU"),
])
def test_a_reply_naming_one_label_is_that_label(reply, label):
    assert ss.parse(reply) == label


@pytest.mark.parametrize("reply", ["", "a wide shot", "CU or MCU", "FS", "INS", "medium",
                                   "the camera is far away", "MCUX"])
def test_a_reply_outside_the_label_list_is_invalid_not_the_nearest_label(reply):
    assert ss.parse(reply) == ss.INVALID


def test_weighted_kappa_matches_the_reference_value_on_a_fixed_confusion_matrix():
    # scikit-learn 1.x cohen_kappa_score(t, p, weights="linear", labels=LADDER), computed outside this repo
    t = ["ECU", "CU", "CU", "MCU", "MS", "MS", "MS", "MLS", "LS", "LS", "ELS", "CU", "MCU", "MS", "LS"]
    p = ["CU", "CU", "MCU", "MCU", "MS", "MLS", "MCU", "MLS", "LS", "ELS", "LS", "CU", "MS", "MS", "MLS"]
    assert ss.kappa(t, p) == pytest.approx(0.7129186602870814, abs=1e-12)
    t2, p2 = ["CU", "MS", "LS", "CU", "MS", "LS"], ["MS", "LS", "ELS", "MCU", "MLS", "ELS"]
    assert ss.kappa(t2, p2) == pytest.approx(0.368421052631579, abs=1e-12)


def test_a_perfect_answer_key_scores_kappa_one_and_its_control_stays_near_zero():
    r = mixed()
    for x in r:
        x["answer"] = x["truth"]
    got = ss.judge(r)
    assert got["kappa"] == 1.0 and got["accuracy"] == 1.0 and got["within_one"] == 1.0
    assert abs(got["control"]["mean"]) < 0.02
    assert got["status"] == "ok"


def test_a_constant_answer_scores_kappa_zero():
    r = mixed()
    for x in r:
        x["answer"] = "MS"
    assert ss.score(r)["kappa"] == pytest.approx(0.0, abs=1e-12)


def test_an_invalid_reply_counts_as_the_widest_disagreement():
    truth = ["CU", "MS", "LS", "CU", "MS", "LS", "ECU", "ELS"]
    right = list(truth)
    refused = list(truth)
    refused[0] = refused[1] = ss.INVALID
    dropped = ss.kappa(truth[2:], right[2:])
    assert ss.kappa(truth, refused) < dropped
    s = ss.score(rows(truth, refused))
    assert s["valid_rate"] == pytest.approx(6 / 8)
    assert s["accuracy"] == pytest.approx(6 / 8) and s["within_one"] == pytest.approx(6 / 8)
    assert s["confusion"]["CU"][ss.INVALID] == 1


def test_the_score_reports_majority_accuracy_and_a_confusion_matrix_per_film():
    r = rows(["CU", "CU", "CU", "LS"], ["CU", "MCU", "CU", "LS"], "a") + rows(["MS", "MS"], ["MS", "LS"], "b")
    s = ss.score(r)
    assert s["n"] == 6 and s["majority"] == pytest.approx(3 / 6)
    assert s["confusion"]["CU"] == {"CU": 2, "MCU": 1}
    assert s["films"]["a"]["n"] == 4 and s["films"]["a"]["accuracy"] == pytest.approx(3 / 4)
    assert s["films"]["b"]["within_one"] == pytest.approx(1 / 2)


def test_a_run_whose_shuffled_control_exceeds_the_bar_is_discarded():
    r = mixed(n=50)
    for x in r:
        x["answer"] = x["truth"]
    # a scorer that pairs answers with a permutation it was handed still sees the true pairing: a leak
    got = ss.judge(r, permute=lambda truth, rng: list(truth))
    assert got["status"] == "discarded" and got["reason"].startswith("control")
    assert "kappa" not in got
    assert ss.judge(r)["status"] == "ok"


def test_an_extra_control_over_the_bar_discards_the_run():
    r = mixed(n=50)
    for x in r:
        x["answer"] = x["truth"]
    got = ss.judge(r, extra_control=[0.4, 0.5])
    assert got["status"] == "discarded" and "trained on shuffled labels" in got["reason"]


def test_the_control_permutes_within_each_film_only():
    seen = []

    def permute(truth, rng):
        seen.append(sorted(truth))
        return ss.shuffled(truth, rng)
    r = rows(["CU"] * 5, ["CU"] * 5, "a") + rows(["LS"] * 5, ["LS"] * 5, "b")
    got = ss.judge(r, permute=permute)
    assert {tuple(s) for s in seen} == {("CU",) * 5, ("LS",) * 5}
    # within a film whose label never varies, a permutation changes nothing
    assert got["control"]["mean"] == pytest.approx(1.0)
    assert got["status"] == "discarded"


# --- cases: the committed stand-in ------------------------------------------------

def test_a_planted_fixture_exam_scores_a_known_kappa(tmp_path):
    frames = vision.load(SHIPPED)
    assert len(frames) == 42 and {f.film for f in frames} == {"synthetic-a", "synthetic-b"}
    got = vision.run_exam(frames, vision.size_labeller, tmp_path, "size")
    assert got["status"] == "ok"
    assert got["kappa"] == 1.0 and got["n"] == 42
    # a labeller one step wide everywhere: every answer adjacent, none exact
    wide = vision.run_exam(frames, lambda fr: [ss.step(vision.size_label(f.path), +1) for f in fr],
                           tmp_path / "wide", "wide")
    assert wide["accuracy"] < 0.2 and wide["within_one"] == 1.0
    assert 0.4 < wide["kappa"] < 0.9


def _pixels(root):
    from PIL import Image
    out = {}
    for m in sorted(Path(root).glob("*/manifest.json")):
        doc = json.loads(m.read_text(encoding="utf-8"))
        for r in doc["frames"]:
            out[r["id"]] = (r["truth"], Image.open(m.parent / r["file"]).convert("RGB").tobytes())
    return out


def test_the_shipped_stand_in_matches_its_generator(tmp_path):
    """Pixels, not PNG bytes: a different zlib may encode the same picture differently."""
    assert _pixels(vision.synthesize(tmp_path)) == _pixels(SHIPPED)


def test_a_missing_frame_is_not_run_not_failed(tmp_path):
    root = tmp_path / "cases"
    shutil.copytree(SHIPPED, root)
    gone = sorted((root / "synthetic-a").glob("*.png"))[0]
    gone.unlink()
    frames = vision.load(root)
    assert sum(f.missing for f in frames) == 1
    got = vision.run_exam(frames, vision.size_labeller, tmp_path / "run", "size")
    assert got["not_run"] == [gone.stem] and got["n"] == 41
    assert got["kappa"] == 1.0


def test_a_machine_with_no_vision_cases_runs_nothing(tmp_path, capsys):
    from harness.commands import vision as cmd
    called = []
    rc = cmd.run_command(cases=None, candidate="size", out=None, label=lambda fr: called.append(fr) or [])
    assert rc == 0 and not called
    assert "not run: no imported vision cases" in capsys.readouterr().out
    assert not (paths.home() / "runs" / "vision").exists()


def test_a_frame_whose_manifest_digest_changed_is_refused(tmp_path):
    root = tmp_path / "cases"
    shutil.copytree(SHIPPED, root)
    one = sorted((root / "synthetic-b").glob("*.png"))[0]
    one.write_bytes(one.read_bytes() + b"x")
    with pytest.raises(ValueError, match="digest"):
        vision.load(root)


# --- alignment ------------------------------------------------------------------

def planted(speed, offset, n=3000, seed=0):
    rng = random.Random(seed)
    labels = []
    while len(labels) < n:
        labels += [rng.randint(1, 7)] * rng.randint(3, 14)
    labels = labels[:n]
    marks = [t for t in range(1, n) if labels[t] != labels[t - 1]]
    change = [rng.uniform(0, 5) for _ in range(int(n * 1.1) + 700)]
    for t in marks:
        o = round(t * speed + offset)
        if 0 < o < len(change):
            change[o] += 30
    return labels, change


@pytest.mark.parametrize("speed,offset", [(1.0, 0), (24 / 25, 0), (25025 / 24000, 7), (1.0, 356), (1.0, -120)])
def test_the_importer_recovers_a_planted_speed_and_offset(speed, offset):
    labels, change = planted(speed, offset)
    a = vision.check_alignment(labels, change)
    assert (a["speed"], a["offset"]) == (speed, offset)
    assert a["accepted"] and a["z"] > vision.ALIGN_MIN_Z


def test_the_importer_rejects_a_mismatched_pair():
    labels, _ = planted(1.0, 0, seed=0)
    _, other = planted(1.0, 0, seed=7)
    assert not vision.check_alignment(labels, other)["accepted"]


def test_alignment_rejects_halves_that_disagree():
    labels, change = planted(1.0, 0)
    for t in range(len(labels) // 2, len(labels)):
        if labels[t] != labels[t - 1]:
            change[t] -= 30
            if t + 90 < len(change):
                change[t + 90] += 30
    assert not vision.check_alignment(labels, change)["accepted"]


def test_alignment_accepts_a_partial_copy_on_the_part_it_holds():
    labels, change = planted(1.0, 12)
    assert vision.check_alignment(labels, change[: len(labels) // 2])["accepted"]


def test_a_sampled_frame_never_sits_on_a_label_change():
    labels = [2, 2, 2, 5, 5, 5, 5, 9, 9, 3, 3, 3, 0, 4]
    ok = vision.eligible(labels, 1.0, 0, n_ours=len(labels))
    assert ok == [1, 4, 5, 10]
    drawn = vision.sample(ok, 3, seed="film-x")
    assert drawn == vision.sample(ok, 3, seed="film-x") and set(drawn) <= set(ok) and len(drawn) == 3


def test_eligible_seconds_stay_inside_the_copy():
    labels = [3] * 20
    assert vision.eligible(labels, 1.0, -5, n_ours=10) == list(range(6, 14))


# --- the importer -------------------------------------------------------------------

def _csv(path, codes):
    lines = [",time,shotscale"] + [f"{i},{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d},{c}"
                                   for i, c in enumerate(codes)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _fake_extract(source, seconds, out_dir, height):
    out = []
    for s in seconds:
        p = out_dir / f"{s:.3f}.png"
        p.write_bytes(f"frame {s}".encode())
        out.append(p)
    return out


def _import(tmp_path, film="film-a", seed=0, stem="Quiet Harbour Nights 1977", change=None):
    labels, planted_change = planted(1.0, 4, seed=seed)
    csv = _csv(tmp_path / f"{stem}.csv", labels)
    src = tmp_path / "library" / f"{stem}.m4v"
    src.parent.mkdir(exist_ok=True)
    if not src.exists():
        src.write_bytes(b"\0" * 4096)
    return vision.import_film(csv, src, film, frames=20,
                              change=lambda p: change or planted_change, extract=_fake_extract), csv, src


def test_the_importer_never_writes_the_source_copy(tmp_path):
    _, _, src = _import(tmp_path)
    before = (src.read_bytes(), src.stat().st_mtime_ns)
    _import(tmp_path, film="film-a")
    assert (src.read_bytes(), src.stat().st_mtime_ns) == before
    assert not any(p for p in src.parent.iterdir() if p != src)


def test_an_import_writes_a_frozen_manifest_under_the_home(tmp_path):
    m, csv, src = _import(tmp_path)
    root = paths.home() / "cases" / "vision" / "film-a"
    on_disk = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == m and m["film"] == "film-a" and len(m["frames"]) == 20
    assert m["alignment"]["speed"] == 1.0 and m["alignment"]["offset"] == 4
    assert m["labels_sha256"] and m["source"]["size"] == 4096 and m["source"]["sha256_ends"]
    text = json.dumps(m)
    assert "Quiet Harbour" not in text and str(src.parent) not in text
    assert {f["truth"] for f in m["frames"]} <= set(L)
    assert all(f["at"] == f["second"] + 4.5 for f in m["frames"])


def test_an_import_registers_the_titles_as_private_names(tmp_path):
    _, csv, src = _import(tmp_path)
    names = privacy.names(ROOT)
    assert "Quiet Harbour Nights 1977" in names and "Quiet Harbour Nights" in names
    assert str(src.parent) in names


def test_a_film_id_holding_a_private_name_is_refused(tmp_path):
    _import(tmp_path)
    with pytest.raises(ValueError, match="private name"):
        _import(tmp_path, film="quiet-harbour-nights")
    with pytest.raises(ValueError, match="film id"):
        _import(tmp_path, film="Not An Id!")


def test_an_unaligned_copy_is_refused_with_its_reason(tmp_path):
    noise = [random.Random(3).uniform(0, 5) for _ in range(4000)]
    with pytest.raises(vision.NotAligned, match="z"):
        _import(tmp_path, change=noise)
    assert not (paths.home() / "cases" / "vision" / "film-a").exists()


def test_a_mismatched_pair_fails_the_import(tmp_path):
    _import(tmp_path, film="film-a", seed=0, stem="First Picture")
    labels_b, change_b = planted(1.0, 4, seed=0)
    # a second film whose picture repeats the first film's cuts: its labels fit the first film's picture too
    with pytest.raises(vision.Mismatched, match="film-a"):
        _import(tmp_path, film="film-b", seed=0, stem="Second Picture")
    assert not (paths.home() / "cases" / "vision" / "film-b").exists()


def test_two_different_films_both_import(tmp_path):
    _import(tmp_path, film="film-a", seed=0, stem="First Picture")
    _import(tmp_path, film="film-b", seed=5, stem="Second Picture")
    assert {f.film for f in vision.load(paths.home() / "cases" / "vision")} == {"film-a", "film-b"}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_the_picture_change_signal_spikes_at_a_cut(tmp_path):
    src = tmp_path / "two.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x36:d=4:r=24",
                    "-f", "lavfi", "-i", "color=c=white:s=64x36:d=4:r=24", "-filter_complex",
                    "[0][1]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", str(src)], check=True)
    before = src.stat().st_mtime_ns
    d = vision.picture_change(src)
    assert len(d) == 8 and max(range(8), key=d.__getitem__) == 4 and d[4] > 100 > max(d[:4] + d[5:])
    frames = vision.extract_frames(src, [1.5, 5.5], tmp_path / "out", height=36)
    assert [p.stat().st_size > 0 for p in frames] == [True, True]
    assert src.stat().st_mtime_ns == before


# --- privacy -------------------------------------------------------------------------

def test_the_privacy_scan_fires_on_a_planted_title(tmp_path):
    privacy.register(["Quiet Harbour Nights"])
    found = privacy.scan("a run over Quiet Harbour Nights scored 0.4", "planted", privacy.name_pattern(ROOT))
    assert found and found[0].name == "person-name"
    assert not privacy.scan("a run over the synthetic stand-in", "planted", privacy.name_pattern(ROOT))


def test_short_or_blank_private_names_are_not_registered_and_none_twice():
    privacy.register(["ab", "  ", "Movies"])
    assert privacy.home_names() == ["Movies"]
    privacy.register(["Movies"])
    assert privacy.home_names() == ["Movies"]


def test_the_export_carries_scores_but_no_title_path_or_frame(tmp_path):
    frames = vision.load(SHIPPED)
    vision.run_exam(frames, vision.size_labeller, None, "size")
    rows_ = vision.export_rows()
    assert [r["candidate"] for r in rows_] == ["size"]
    r = rows_[0]
    assert r["kappa"] == 1.0 and r["frames"] == 42 and r["films"] == 2 and r["status"] == "ok"
    assert "CC BY 4.0" in r["labels"] and "10.17632/th46h4vdwd.1" in r["labels"]
    text = json.dumps(rows_)
    for leak in ("synthetic-a", ".png", str(paths.home()), "/"):
        assert leak not in text.replace("CC BY 4.0", "").replace("10.17632/th46h4vdwd.1", ""), leak


def test_the_export_refuses_a_vision_row_naming_a_private_title(tmp_path):
    privacy.register(["Quiet Harbour Nights"])
    doc = {"vision": [{"candidate": "hf-vlm:org/Quiet-Harbour-Nights", "note": "Quiet Harbour Nights"}]}
    with pytest.raises(publish.ExportRefused):
        publish.checked(doc)


def test_the_benchmarks_page_shows_the_vision_scores_and_credits_cinescale():
    from harness import site
    vision.run_exam(vision.load(SHIPPED), vision.size_labeller, None, "size")
    doc = {"machine": {"label": "Test Box"}, "lanes": [], "vision": vision.export_rows()}
    html = site.benchmarks([doc])
    assert 'id="lane-vision"' in html and "size" in html and "1.000" in html
    assert "10.17632/th46h4vdwd.1" in html and "CC BY 4.0" in html
    assert "vision" not in site.benchmarks([{"machine": {"label": "Test Box"}, "lanes": []}])


def test_the_machine_export_has_a_vision_key(tmp_path):
    vision.run_exam(vision.load(SHIPPED), vision.size_labeller, None, "size")
    doc = publish.export()
    assert doc["vision"][0]["candidate"] == "size"


# --- the probe ---------------------------------------------------------------------

def size_features(path):
    """Share of dark pixels: the stand-in's subject size, a one-number feature a probe can learn."""
    from PIL import Image
    g = Image.open(path).convert("L")
    return [sum(1 for v in g.tobytes() if v < 128) / (g.width * g.height)]


def centroid_fit(X, y, c):
    """Nearest class mean: the probe's wiring under test, not its optimiser."""
    means = {}
    for label in set(y):
        pts = [x for x, t in zip(X, y) if t == label]
        means[label] = [sum(col) / len(pts) for col in zip(*pts)]
    return lambda xs: [min(means, key=lambda k: sum((a - b) ** 2 for a, b in zip(x, means[k]))) for x in xs]


def test_the_probe_beats_its_own_shuffled_label_control_on_the_fixture(tmp_path):
    frames = vision.load(SHIPPED)
    feats = {f.id: size_features(f.path) for f in frames}
    preds = vision.probe_predictions(frames, feats, shuffles=3, seed=1207, fit=centroid_fit)
    got = vision.score_probe(frames, preds, tmp_path, "probe:size")
    assert got["status"] == "ok" and got["kappa"] > 0.9
    assert len(got["probe_control"]) == 3 and all(abs(k) < 0.5 for k in got["probe_control"])
    assert got["reference"] is True


def test_a_probe_whose_shuffled_training_still_scores_is_discarded(tmp_path):
    frames = vision.load(SHIPPED)
    feats = {f.id: size_features(f.path) for f in frames}
    truth = {f.id: f.truth for f in frames}
    preds = {"answers": dict(truth), "control": [dict(truth), dict(truth)]}
    got = vision.score_probe(frames, preds, tmp_path, "probe:leaky")
    assert got["status"] == "discarded" and "shuffled labels" in got["reason"]
    assert feats


def test_the_probe_is_trained_without_the_film_it_is_tested_on():
    frames = vision.load(SHIPPED)
    seen = []

    def fit(X, y, c):
        seen.append((len(X), c))
        return lambda x: [y[0]] * len(x)
    feats = {f.id: size_features(f.path) for f in frames}
    vision.probe_predictions(frames, feats, shuffles=0, seed=0, fit=fit)
    assert seen == [(21, vision.PROBE_C), (21, vision.PROBE_C)]


# --- the hf-task runner -------------------------------------------------------------

def test_vision_label_writes_one_answer_per_frame_and_resumes(tmp_path):
    from harness import hf_task
    frames = tmp_path / "frames.jsonl"
    frames.write_text("".join(json.dumps({"id": f"f{i}", "image": f"/x/{i}.png"}) + "\n" for i in range(3)),
                      encoding="utf-8")
    out = tmp_path / "answers.jsonl"
    out.write_text(json.dumps({"id": "f0", "reply": "CU"}) + "\n", encoding="utf-8")
    asked = []

    def label(model, images, prompt):
        asked.extend(images)
        return ["MS" for _ in images]
    rc = hf_task.main(["vision-label", "--model", "org/vlm", "--frames", str(frames), "--prompt", "p",
                       "--out", str(out)], label=label)
    assert rc == 0 and asked == ["/x/1.png", "/x/2.png"]
    got = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert [g["id"] for g in got] == ["f0", "f1", "f2"] and got[0]["reply"] == "CU"


def test_a_frame_hf_task_left_unanswered_is_the_harness_not_the_model(tmp_path, monkeypatch):
    from harness.commands import vision as cmd
    frames = vision.load(SHIPPED)[:2]

    def fake_run(argv, check=False):
        out = Path(argv[argv.index("--out") + 1])
        out.write_text(json.dumps({"id": frames[0].id, "reply": "CU"}) + "\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(cmd.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="answered 1 of 2"):
        cmd.hf_vlm("org/vlm", tmp_path)(frames)


def test_the_probe_feature_cache_follows_frame_content_not_its_id(tmp_path):
    root = tmp_path / "cases"
    shutil.copytree(SHIPPED, root)
    before = vision.features_cache("m", vision.load(root))
    m = root / "synthetic-a" / "manifest.json"
    doc = json.loads(m.read_text(encoding="utf-8"))
    p = root / "synthetic-a" / doc["frames"][0]["file"]
    p.write_bytes(p.read_bytes() + b"\0")
    doc["frames"][0]["sha256"] = vision._sha(p)
    doc["digest"] = vision._digest(doc["frames"])
    m.write_text(json.dumps(doc), encoding="utf-8")
    assert vision.features_cache("m", vision.load(root)) != before


def test_the_vision_prompt_names_every_label_on_the_ladder():
    for label in L:
        assert label in ss.PROMPT
    assert "FS" not in ss.PROMPT.split() and "INS" not in ss.PROMPT.split()
