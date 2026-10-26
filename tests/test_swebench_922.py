"""#922: the seam between our generation path and the official SWE-bench grader, and the comparison over it."""
import argparse
import json
import subprocess
from pathlib import Path

import pytest

from evals import repo, swebench
from tests import shells

GOLD = ("diff --git a/pkg/mod.py b/pkg/mod.py\n--- a/pkg/mod.py\n+++ b/pkg/mod.py\n"
        "@@ -1,3 +1,3 @@\n def f(x):\n-    return x\n+    return x + 1\n \n")


def _through_the_seam(tmp_path: Path, reply: str) -> str:
    out = tmp_path / "predictions.jsonl"
    swebench.write_jsonl(out, [swebench.prediction("o__r-1", "m", repo.extract_diff(reply))])
    (row,) = swebench.read_jsonl(out)
    assert set(row) == {"instance_id", "model_name_or_path", "model_patch"}
    return row["model_patch"]


def test_a_swellama_patch_tag_reply_reaches_predictions_as_the_gold_bytes(tmp_path):
    reply = "<patch>\n" + GOLD + "</patch>"
    assert _through_the_seam(tmp_path, reply) == GOLD


def test_a_truncated_patch_tag_reply_keeps_what_it_has_without_the_tag(tmp_path):
    got = _through_the_seam(tmp_path, "<patch>\n" + GOLD)
    assert got == GOLD


def test_a_fenced_gold_patch_reaches_predictions_as_the_gold_bytes(tmp_path):
    reply = "Here is the fix.\n\n```diff\n" + GOLD + "```\nThat should do it."
    assert _through_the_seam(tmp_path, reply) == GOLD


def test_the_harness_extractor_port_returns_the_tag_body_as_published():
    assert swebench.harness_extract_diff("<patch>\n" + GOLD + "</patch>") == "\n" + GOLD
    assert swebench.harness_extract_diff("```diff\n" + GOLD + "```") == GOLD
    assert swebench.harness_extract_diff("no diff</s>junk") == "no diff"


def _results():
    return {"generated": [f"r__a-{i}" for i in range(12)] + [f"r__b-{i}" for i in range(8)],
            "no_generation": ["r__c-0"], "reset_failed": ["r__a-0"], "install_fail": ["r__b-0"],
            "applied": ["r__a-1", "r__a-2", "r__b-1"], "resolved": ["r__a-1"]}


def _verified():
    rows = [{"instance_id": f"r__a-{i}", "repo": "r/a", "difficulty": "<15 min fix" if i % 2 else "15 min - 1 hour"}
            for i in range(12)]
    rows += [{"instance_id": f"r__b-{i}", "repo": "r/b", "difficulty": "<15 min fix"} for i in range(8)]
    rows += [{"instance_id": "r__c-0", "repo": "r/c", "difficulty": "<15 min fix"},
             {"instance_id": "r__d-0", "repo": "r/d", "difficulty": "<15 min fix"}]
    return rows


def test_the_sample_is_seeded_stratified_and_excludes_what_the_reference_could_not_compare():
    got = swebench.draw(_verified(), _results(), n=9, seed=7)
    assert got == swebench.draw(_verified(), _results(), n=9, seed=7)
    assert got["n"] == 9 and len(set(got["ids"])) == 9
    assert not {"r__a-0", "r__b-0", "r__c-0", "r__d-0"} & set(got["ids"])
    assert got["excluded"] == {"reset_failed": 1, "install_fail": 1, "no_generation": 1, "not_in_reference": 1}
    drawn = {(s["repo"], s["difficulty"]): s["drawn"] for s in got["strata"]}
    # eligible: a/<15 6, a/15-60 5, b/<15 7 -> 18; 9 of them proportionally is 3, 2.5, 3.5
    assert drawn == {("r/a", "<15 min fix"): 3, ("r/a", "15 min - 1 hour"): 2, ("r/b", "<15 min fix"): 4}
    assert swebench.draw(_verified(), _results(), n=9, seed=8)["ids"] != got["ids"]


def test_sample_writes_the_ids_the_seed_and_the_reference_it_drew_against(tmp_path):
    verified = tmp_path / "verified.jsonl"
    swebench.write_jsonl(verified, _verified())
    results = tmp_path / "results.json"
    results.write_text(json.dumps(_results()), encoding="utf-8")
    run = tmp_path / "run"
    assert swebench.main(["sample", str(run), "--n", "5", "--seed", "3", "--verified", str(verified),
                          "--results", str(results), "--no-reference-preds"]) == 0
    got = swebench.read_json(run / "sample.json")
    assert got["seed"] == 3 and got["n"] == 5
    assert got["sources"]["verified"]["revision"] == swebench.VERIFIED[1]
    assert swebench.read_json(run / "reference" / "results.json") == _results()


def _run_dir(tmp_path: Path, ids) -> Path:
    run = tmp_path / "run"
    swebench.write_json(run / "sample.json", {"ids": list(ids), "seed": 1, "n": len(ids)})
    return run


def test_predict_sends_the_prompt_verbatim_and_records_its_configuration(tmp_path):
    run = _run_dir(tmp_path, ["o__r-1", "o__r-2"])
    prompts = tmp_path / "prompts.jsonl"
    swebench.write_jsonl(prompts, [{"instance_id": "o__r-1", "text": "Fix it.\n"},
                                   {"instance_id": "o__r-2", "text": "Fix that.\n\n"},
                                   {"instance_id": "o__r-9", "text": "never asked"}])
    sent = []

    def post(url, payload):
        sent.append((url, payload))
        return {"content": "<patch>\n" + GOLD + "</patch>", "tokens_predicted": 40, "stop_type": "eos",
                "generation_settings": {"temperature": 0.0, "samplers": ["top_k"]}}

    def get(url):
        assert url.endswith("/props")
        return {"build_info": "b9999-abc", "model_path": "/m/SWE-Llama-13b-Q8_0.gguf",
                "default_generation_settings": {"n_ctx": 32768}}

    args = argparse.Namespace(run_dir=str(run), server="http://127.0.0.1:1", model="m", weights="w",
                              quant="", prompts=str(prompts), max_tokens=123, limit=0)
    assert swebench.cmd_predict(args, post=post, get=get) == 0
    assert [p["prompt"] for _, p in sent] == ["Fix it.\n\n", "Fix that.\n\n"]
    assert all(u.endswith("/completion") and p["n_predict"] == 123 and p["temperature"] == 0.0 for u, p in sent)
    receipt = swebench.read_json(run / "receipt.json")
    assert receipt["quant"] == "Q8_0" and receipt["server"]["build_info"] == "b9999-abc"
    assert receipt["prompts"]["revision"] == swebench.PROMPTS[1] and receipt["harness"] == swebench.HARNESS_PIN
    assert receipt["sampling"] == swebench.GREEDY and receipt["replies"] == 2
    assert receipt["served_sampling"] == {"temperature": 0.0, "samplers": ["top_k"]}, "what the server applied, not only what we asked"
    preds = swebench.read_jsonl(run / "predictions.jsonl")
    assert [p["model_patch"] for p in preds] == [GOLD, GOLD]
    assert swebench.read_jsonl(run / "predictions.upstream.jsonl")[0]["model_patch"] == "\n" + GOLD
    swebench.cmd_predict(args, post=post, get=get)
    assert len(sent) == 2, "a rerun asks only for the ids with no stored reply"


def test_the_null_control_applies_with_git_and_touches_no_tracked_file(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    got = subprocess.run(["git", "apply", "--verbose", "-"], cwd=tmp_path, input=swebench.NULL_PATCH.encode(),
                         capture_output=True)
    assert got.returncode == 0, got.stderr
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert swebench.NULL_PATCH.strip(), "the harness skips an empty patch instead of grading it"


def test_grade_writes_a_hand_off_with_both_controls_and_the_model_run(tmp_path):
    ids = ["o__r-1", "o__r-2"]
    run = _run_dir(tmp_path, ids)
    swebench.write_jsonl(run / "predictions.jsonl", [swebench.prediction("o__r-1", "m", GOLD),
                                                    swebench.prediction("o__r-2", "m", "")])
    swebench.write_jsonl(run / "predictions.upstream.jsonl", [swebench.prediction("o__r-1", "m", "\n" + GOLD),
                                                             swebench.prediction("o__r-2", "m", "")])
    assert swebench.main(["grade", str(run)]) == 0
    script = (run / "grade" / "grade.sh").read_text(encoding="utf-8")
    assert f"pip install -q {swebench.HARNESS_PIN}" in script
    assert "run gold gold o__r-1 o__r-2" in script
    assert "run null grade/null.jsonl o__r-1 o__r-2" in script
    assert "run model predictions.jsonl o__r-1\n" in script
    assert "run upstream" not in script, "the extractors agree once leading newlines are set aside"
    assert 'uname -m)" != x86_64' in script
    nulls = swebench.read_jsonl(run / "grade" / "null.jsonl")
    assert {n["model_patch"] for n in nulls} == {swebench.NULL_PATCH}
    sh = shells.resolve("sh")
    if sh:
        assert subprocess.run([sh, "-n", str(run / "grade" / "grade.sh")]).returncode == 0


def _grade(run: Path, kind: str, model: str, outcomes: dict) -> None:
    for iid, got in outcomes.items():
        inst = run / "grades" / kind / model / iid
        inst.mkdir(parents=True)
        if got == "no_apply":
            (inst / "run_instance.log").write_text(f"x\n{swebench.APPLY_PATCH_FAIL}:\nerror\n", encoding="utf-8")
        elif got == "error":
            (inst / "run_instance.log").write_text("docker build failed\n", encoding="utf-8")
        else:
            applied, resolved = got
            swebench.write_json(inst / "report.json", {iid: {"patch_successfully_applied": applied,
                                                             "resolved": resolved}})


def test_compare_on_known_overlaps_prints_known_counts(tmp_path, capsys):
    ids = [f"o__r-{i}" for i in range(1, 11)]
    run = _run_dir(tmp_path, ids)
    # reference: applied 1,2,3,4,5 and 9; resolved 1
    swebench.write_json(run / "reference" / "results.json",
                        {"generated": ids, "applied": ["o__r-1", "o__r-2", "o__r-3", "o__r-4", "o__r-5", "o__r-9"],
                         "resolved": ["o__r-1"]})
    swebench.write_jsonl(run / "predictions.jsonl",
                         [swebench.prediction(i, "m", "" if i == "o__r-8" else GOLD) for i in ids])
    gold = {i: (True, True) for i in ids}
    gold["o__r-10"] = (True, False)
    _grade(run, "gold", "gold", gold)
    null = {i: (True, False) for i in ids}
    null["o__r-9"] = (True, True)
    _grade(run, "null", "sohot-null", null)
    # ours: applied 1,2,3,6,7; 4 and 5 fail to apply; 8 empty; resolved 1 and 6
    _grade(run, "model", "m", {"o__r-1": (True, True), "o__r-2": (True, False), "o__r-3": (True, False),
                               "o__r-4": "no_apply", "o__r-5": "no_apply", "o__r-6": (True, True),
                               "o__r-7": (True, False), "o__r-9": (True, False), "o__r-10": "error"})
    assert swebench.main(["compare", str(run), "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["dropped"] == {"o__r-10": "gold did not resolve", "o__r-9": "null patch resolved"}
    assert got["retained"] == 8
    applied = got["vs_published"]["applied"]
    assert (applied["both"], applied["only_ours"], applied["only_theirs"], applied["neither"]) == (3, 2, 2, 1)
    assert (applied["ours"], applied["theirs"], applied["agreement"]) == (5, 5, 0.5)
    assert applied["mcnemar_p"] == 1.0 and applied["agrees"]
    resolved = got["vs_published"]["resolved"]
    assert (resolved["both"], resolved["only_ours"], resolved["only_theirs"]) == (1, 1, 0)
    assert resolved["diff"] == 0.125 and not resolved["agrees"]
    assert swebench.main(["compare", str(run)]) == 0
    text = capsys.readouterr().out
    assert "retained 8 after controls; dropped 2" in text
    assert "applied  ours 5/8 62.5%" in text and "discordant 2/2  McNemar p=1.0000  within margin" in text


def test_compare_before_grading_says_pending_and_still_reports_extraction(tmp_path, capsys):
    run = _run_dir(tmp_path, ["o__r-1", "o__r-2"])
    swebench.write_json(run / "reference" / "results.json", {"generated": ["o__r-1", "o__r-2"]})
    swebench.write_jsonl(run / "predictions.jsonl", [swebench.prediction("o__r-1", "m", GOLD)])
    swebench.write_jsonl(run / "reference" / "all_preds.jsonl", [swebench.prediction("o__r-1", "ref", "\n" + GOLD)])
    assert swebench.main(["compare", str(run)]) == 2
    text = capsys.readouterr().out
    assert "grading pending" in text
    assert "with_patch 1" in text and "identical_to_reference 1" in text and "same_files_as_reference 1" in text


def test_a_patch_without_git_lines_still_names_its_files():
    assert swebench._files(GOLD.replace("diff --git a/pkg/mod.py b/pkg/mod.py\n", "")) == swebench._files(GOLD)
    assert swebench._files(GOLD) == {"pkg/mod.py"}


@pytest.mark.network
def test_the_reference_results_and_predictions_are_still_published():
    results = json.loads(swebench._fetch(swebench.RESULTS_URL))
    assert len(results["applied"]) == 190 and len(results["resolved"]) == 6
    preds = [json.loads(line) for line in swebench._fetch(swebench.PREDS_URL).decode().splitlines() if line]
    assert len(preds) == 481 and {"instance_id", "model_patch"} <= set(preds[0])


BASE = "def f(x):\n    return x\n\n\ndef g():\n    pass\n"
FUZZY = "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -1,3 +1,3 @@\n def f(y):\n-    return x\n+    return x + 1\n \n"


def _origin(root: Path) -> tuple[Path, str]:
    src = root / "r" / "a"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "mod.py").write_text(BASE, encoding="utf-8")
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(src)]
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "base"], check=True)
    base = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    (src / "pkg" / "mod.py").write_text("changed later\n", encoding="utf-8")
    subprocess.run([*git, "commit", "-qam", "later"], check=True)
    return src, base


def test_the_apply_check_follows_the_harness_chain_down_to_patch_fuzz(tmp_path):
    src, base = _origin(tmp_path / "src")
    tree = swebench.checkout(str(src), base, tmp_path / "cache" / "r__a")
    assert swebench.apply_check(tree, base, GOLD) == {"applied": True, "by": "git apply --verbose"}
    assert (tree / "pkg" / "mod.py").read_text(encoding="utf-8") == BASE, "each check starts from a pristine base"
    assert swebench.apply_check(tree, base, FUZZY) == {"applied": True, "by": "patch --batch --forward --fuzz=5 -p1 -i"}
    assert swebench.apply_check(tree, base, "no diff here\n")["applied"] is False
    assert swebench.apply_check(tree, base, "") == {"applied": False, "by": "empty"}
    assert swebench.APPLY_CMDS[0] == "git apply --verbose" and len(swebench.APPLY_CMDS) == 4


def test_apply_writes_each_kind_per_id_checked_on_a_clone_at_its_base(tmp_path):
    src, base = _origin(tmp_path / "src")
    ids = ["r__a-1", "r__a-2"]
    run = _run_dir(tmp_path, ids)
    rows = tmp_path / "verified.jsonl"
    swebench.write_jsonl(rows, [{"instance_id": i, "repo": "r/a", "base_commit": base, "patch": GOLD} for i in ids])
    swebench.write_jsonl(run / "predictions.jsonl", [swebench.prediction("r__a-1", "m", FUZZY),
                                                    swebench.prediction("r__a-2", "m", "")])
    swebench.write_jsonl(run / "reference" / "all_preds.jsonl", [swebench.prediction("r__a-1", "ref", "junk\n")])
    source = str(tmp_path / "src") + "/{repo}"
    assert swebench.main(["apply", str(run), "--verified", str(rows), "--source", source]) == 0
    got = swebench.read_json(run / "grades" / "apply.json")
    assert got["chain"] == list(swebench.APPLY_CMDS)
    assert {k: {i: v["applied"] for i, v in got["kinds"][k].items()} for k in ("gold", "model", "reference")} == {
        "gold": {"r__a-1": True, "r__a-2": True}, "model": {"r__a-1": True, "r__a-2": False},
        "reference": {"r__a-1": False}}
    assert "upstream" not in got["kinds"], "a kind with no predictions file is not checked"


def test_compare_reports_the_apply_check_when_no_docker_grades_exist(tmp_path, capsys):
    ids = [f"o__r-{i}" for i in range(1, 7)]
    run = _run_dir(tmp_path, ids)
    swebench.write_json(run / "reference" / "results.json",
                        {"generated": ids, "applied": ["o__r-1", "o__r-2", "o__r-3"], "resolved": []})
    swebench.write_jsonl(run / "predictions.jsonl", [swebench.prediction(i, "m", GOLD) for i in ids])
    gold = {i: True for i in ids}
    gold["o__r-6"] = False
    ours = {"o__r-1": True, "o__r-2": True, "o__r-3": False, "o__r-4": True, "o__r-5": False, "o__r-6": True}
    ref = {"o__r-1": True, "o__r-2": True, "o__r-3": True, "o__r-4": False, "o__r-5": False, "o__r-6": True}
    swebench.write_json(run / "grades" / "apply.json", {"chain": list(swebench.APPLY_CMDS), "kinds": {
        k: {i: {"applied": v, "by": ""} for i, v in d.items()} for k, d in (("gold", gold), ("model", ours),
                                                                          ("reference", ref))}})
    assert swebench.main(["compare", str(run), "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    check = got["apply_check"]
    assert check["dropped"] == {"o__r-6": "gold patch did not apply here"} and check["retained"] == 5
    mine = check["ours_vs_reference"]
    assert (mine["both"], mine["only_ours"], mine["only_theirs"], mine["neither"]) == (2, 1, 1, 1)
    drift = check["reference_vs_published"]
    assert (drift["both"], drift["only_ours"], drift["only_theirs"]) == (3, 0, 0) and drift["agreement"] == 1.0
    assert got["status"] == "applied_only"
    assert swebench.main(["compare", str(run)]) == 0
    text = capsys.readouterr().out
    assert "applied here, no Docker: retained 5 of 6 after the gold control" in text
    assert "ours vs reference (both checked here)" in text
