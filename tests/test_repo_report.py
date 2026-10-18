"""The repo-lane report counts tasks, not cases: spec and symptom of one fix are one unit. #923."""
from __future__ import annotations

import random
import re
from types import SimpleNamespace

import pytest

from evals import compare, repo_report as R
from harness import paired, power

BASE, CAND = "base-model", "challenger"
CODES = {"P": (True, ""), "I": (False, "invalid_patch"), "C": (False, "content_failed"),
         "T": (False, "token_budget_exhausted"), "E": (False, "environment_error")}
#: Pilot runs 466 (Ornith) and 467 (Opus) from the store: case -> Ornith code, Opus code.
PILOT = """sohot-318-omnisvg-spelling|PP sohot-363-spec|IP sohot-363-symptom|IC sohot-368-spec|II
sohot-368-symptom|TC sohot-371-spec|TI sohot-371-symptom|TI sohot-374-spec|IP sohot-374-symptom|IP
sohot-376-spec|CP sohot-376-symptom|TP sohot-396-spec|CC sohot-396-symptom|TC sohot-399-spec|TI
sohot-399-symptom|IC sohot-404-spec|TI sohot-404-symptom|TC sohot-438-spec|TC sohot-438-symptom|CC
sohot-455-spec|TC sohot-455-symptom|TC sohot-570-spec|PP sohot-570-symptom|PP sohot-598-spec|EE
sohot-598-symptom|EE sohot-632-spec|TC sohot-632-symptom|TC sohot-642-spec|TC sohot-642-symptom|IC
sohot-647-spec|TC sohot-647-symptom|IC sohot-720-spec|PP sohot-720-symptom|CP sohot-788-spec|IP
sohot-788-symptom|IP sohot-858-spec|EE sohot-858-symptom|EE sohot-859-spec|TC sohot-859-symptom|TC
sohot-879-spec|TI sohot-879-symptom|TI"""
ORNITH, OPUS = "llamacpp:Ornith-1.5-35B-Q4_K_M", "claude-code:claude-opus-5-5"
#: Two-run sides are keyed by run, not spec. #975.
BASE_SIDE, CAND_SIDE, ORNITH_SIDE, OPUS_SIDE = f"run 1 {BASE}", f"run 2 {CAND}", f"run 466 {ORNITH}", f"run 467 {OPUS}"


def _case(cid, fix, variant):
    return SimpleNamespace(id=cid, params={"fix": fix, "variant": variant})


def _runs(*ids):
    return [{"id": i, "lane": "repo", "repeat": 1, "cases_digest": "d", "receipt": {"modality": "repo"},
             "environment": {}, "generated_at": None} for i in ids]


def _row(run, cand, cid, code):
    passed, fc = CODES[code]
    return {"run_id": run, "candidate": cand, "case_id": cid, "repeat_index": 1, "passed": passed,
            "failure_class": fc, "hit_limit": ""}


def _suite(outcomes, **kw):
    """outcomes: per task, (base spec, base symptom, cand spec, cand symptom) codes; two runs."""
    cases, rows = [], []
    for t, codes in enumerate(outcomes):
        for v, (b, c) in zip(R.VARIANTS, ((codes[0], codes[2]), (codes[1], codes[3]))):
            cid = f"t{t}-{v}"
            cases.append(_case(cid, f"{t:040x}", v))
            rows += [_row(1, BASE, cid, b), _row(2, CAND, cid, c)]
    return R.report(_runs(1, 2), rows, cases, resamples=kw.get("resamples", 2000), seed=1)


def _losses(rep):
    return rep["views"]["limits as losses"]


def test_two_identical_candidates_never_differ():
    rng = random.Random(7)
    outcomes = []
    for _ in range(20):
        a, b = rng.choice("PC"), rng.choice("PC")
        outcomes.append((a, b, a, b))
    v = _losses(_suite(outcomes))
    assert v["discordant"] == 0 and v["p"] == 1.0 and v["verdict"] != "differs"
    assert v["difference"] == {"difference": 0.0, "low": 0.0, "high": 0.0}


def test_three_task_wins_on_both_variants_do_not_reject_though_six_case_wins_would():
    v = _losses(_suite([("C", "C", "P", "P")] * 3 + [("C", "C", "C", "C")] * 17))
    assert paired.sign_test(0, 6) == pytest.approx(0.03125)
    assert (len(v["only"][CAND_SIDE]), len(v["only"][BASE_SIDE])) == (3, 0)
    assert v["p"] == 0.25 and v["verdict"] == "untestable at 3 discordant"
    assert v["difference"]["low"] <= 0.0


def test_ten_discordant_tasks_one_way_reject_and_the_interval_excludes_zero():
    v = _losses(_suite([("C", "C", "P", "P")] * 10 + [("C", "C", "C", "C")] * 10))
    assert v["p"] == 0.002 and v["verdict"] == "differs"
    assert v["difference"]["low"] > 0.0


def _simulate(rng, tasks):
    """Each candidate resolves a task w.p. 0.5 / 0.3; a resolved task resolves each variant w.p. 0.9."""
    by, clusters = {"a": {}, "b": {}}, {}
    for t in range(tasks):
        on = {"a": rng.random() < 0.5, "b": rng.random() < 0.3}
        for v in R.VARIANTS:
            cid = f"{t}-{v}"
            clusters[cid] = t
            for who in by:
                by[who][cid] = (float(on[who] and rng.random() < 0.9), 1.0)
    return by, sorted(clusters), clusters


def _coverage(clustered: bool, draws: int) -> float:
    rng, truth, hit = random.Random(923), (0.5 - 0.3) * 0.9, 0
    for i in range(draws):
        by, cases, clusters = _simulate(rng, 40)
        iv = compare.interval(by, cases, "a", "b", resamples=400, seed=i, clusters=clusters if clustered else None)
        hit += iv["low"] <= truth <= iv["high"]
    return hit / draws


def test_the_task_bootstrap_covers_a_known_difference_at_its_nominal_rate():
    assert 0.93 <= _coverage(True, 1000) <= 0.97


def test_a_case_bootstrap_of_clustered_variants_under_covers():
    assert _coverage(False, 300) < 0.90


def test_a_task_is_its_fix_commit_not_its_case_name():
    cases = [_case("alpha-spec", "a" * 40, "spec"), _case("beta", "a" * 40, "symptom"),
             _case("gamma-spec", "b" * 40, "spec"), _case("gamma-symptom", "c" * 40, "symptom")]
    rows = [_row(r, c, k.id, "P") for k in cases for r, c in ((1, BASE), (2, CAND))]
    rep = R.report(_runs(1, 2), rows, cases, resamples=50)
    assert {t for t, _ in R.tasks_of(cases).values()} == {"a" * 40, "b" * 40, "c" * 40}
    assert _losses(rep)["tasks"] == 1 and _losses(rep)["cases"] == 2
    assert rep["set_aside"]["single_variant"] == ["gamma-spec", "gamma-symptom"]


def _pilot_rows():
    rows = []
    for item in PILOT.split():
        cid, codes = item.split("|")
        rows += [_row(466, ORNITH, cid, codes[0]), _row(467, OPUS, cid, codes[1])]
    return rows


def _repo_cases():
    """The 41 cases the pilot ran on, the ones #920 dropped afterwards included."""
    from evals.core import Case, load_cases
    from evals.importers import CASES, history
    held = dict(history.DROPPED)
    history.DROPPED.clear()
    try:
        made = [history.convert(r).case for r in history.fetch()]
    finally:
        history.DROPPED.update(held)
    own = [c for c in load_cases(CASES / "repo") if "history" not in c.source.parts]
    return own + [Case(id=c["id"], modality=c["modality"], prompt=c["prompt"], params=c["params"]) for c in made]


def test_the_pilot_reads_as_the_store_does():
    rep = R.report(_runs(466, 467), _pilot_rows(), _repo_cases(), resamples=500)
    v = _losses(rep)
    assert (rep["baseline"], rep["candidate"]) == (ORNITH_SIDE, OPUS_SIDE)
    assert (v["rates"][OPUS_SIDE]["all"]["resolved"], v["rates"][OPUS_SIDE]["all"]["n"]) == (11, 36)
    assert (v["rates"][ORNITH_SIDE]["all"]["resolved"], v["rates"][ORNITH_SIDE]["all"]["n"]) == (3, 36)
    f = rep["fair"]["views"]["limits as losses"]
    assert (f["cases"], f["tasks"]) == (12, 7) and "sohot-858-spec" in rep["fair"]["unfair"]
    assert (f["rates"][OPUS_SIDE]["all"]["resolved"], f["rates"][ORNITH_SIDE]["all"]["resolved"]) == (9, 3)
    assert "limits as losses, fair subset: 12 cases from 7 tasks" in R.text(rep)
    assert v["rates"][OPUS_SIDE]["all"]["ci95"] == [0.18, 0.4686] and v["rates"][ORNITH_SIDE]["all"]["ci95"] == [0.0287, 0.2183]
    named = {rep["labels"][t] for t in v["only"][OPUS_SIDE]}
    assert named == {"sohot-363", "sohot-374", "sohot-376", "sohot-788"} and v["only"][ORNITH_SIDE] == []
    assert {rep["labels"][t] for t in v["both"]} == {"sohot-570", "sohot-720"}
    # Per-task pass rate is the paired unit (#995): sohot-720 is both variants for Opus, the spec for Ornith.
    assert {rep["labels"][t] for t in v["higher"][OPUS_SIDE]} == named | {"sohot-720"} and v["higher"][ORNITH_SIDE] == []
    assert v["p"] == 0.0625 and v["verdict"] == "untestable at 5 discordant"
    for c, task in ((OPUS_SIDE, "sohot-363"), (ORNITH_SIDE, "sohot-720")):
        g = v["gap"][c]
        assert [rep["labels"][t] for t in g["spec_only"]] == [task] and g["symptom_only"] == []
        assert g["verdict"] == "untestable at 1 discordant" and "difference" not in g
    assert rep["excluded_never_ran"] == ["sohot-598-spec", "sohot-598-symptom", "sohot-858-spec",
                                         "sohot-858-symptom"]
    assert rep["set_aside"]["single_variant"] == ["sohot-318-omnisvg-spelling"]
    assert rep["limit_rows"] == {ORNITH_SIDE: 19, OPUS_SIDE: 0}
    assert not v["power"][OPUS_SIDE]["rho_measured"] and v["power"][OPUS_SIDE]["rho_used"] == power.DEFAULT_RHO
    assert rep["views"]["limits unjudged"]["cases"] == 17
    assert "untestable at 5 discordant" in R.text(rep)


def test_tasks_needed_is_power_cases_needed_on_the_same_rates():
    outcomes = [("C", "P" if t < 5 else "C", "C", "C") for t in range(20)]
    v = _losses(_suite(outcomes, resamples=50))
    rates = [1.0] * 5 + [0.0] * 15
    want = power.cases_needed(rates, 0.2, rho=1.0, stochastic=False, alpha=0.05)
    assert want == 52 and v["power"][BASE_SIDE]["symptom"]["needed"]["0.2"] == want


def test_a_limit_counts_as_a_loss_in_one_view_and_drops_out_in_the_other():
    v = _suite([("T", "C", "P", "C")] + [("C", "C", "C", "C")] * 3, resamples=50)["views"]
    assert v["limits as losses"]["only"][CAND_SIDE] and v["limits as losses"]["cases"] == 8
    assert not v["limits unjudged"]["only"][CAND_SIDE] and v["limits unjudged"]["cases"] == 7


def test_two_runs_over_different_case_sets_are_refused():
    runs = _runs(1, 2)
    runs[1]["cases_digest"] = "other"
    with pytest.raises(R.Refused, match="different case sets"):
        R.check_runs(runs, [])


def test_a_run_of_another_lane_is_refused():
    runs = _runs(1)
    runs[0]["receipt"]["modality"] = "code"
    with pytest.raises(R.Refused, match="not a repo-lane run"):
        R.check_runs(runs, [])


def test_a_run_whose_case_files_changed_is_refused():
    from evals.core import cases_digest
    cases = _repo_cases()
    runs = _runs(1)
    runs[0]["receipt"]["case_ids"] = [c.id for c in cases]
    runs[0]["cases_digest"] = cases_digest(cases)
    R.check_runs(runs, cases)
    runs[0]["cases_digest"] = "0" * 16
    with pytest.raises(R.Refused, match="differ from the local case files"):
        R.check_runs(runs, cases)


def test_cases_edited_since_the_run_are_read_back_from_its_commit(tmp_path):
    import shutil
    import subprocess

    from evals.core import cases_digest, load_cases
    from evals.importers import CASES
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=CASES).stdout.strip()
    if not sha or subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "."], cwd=CASES / "repo").returncode:
        pytest.skip("needs a git checkout whose repo cases match HEAD")
    committed = R.cases_at(sha)
    shutil.copytree(CASES / "repo", tmp_path / "repo")
    edited = next((tmp_path / "repo" / "history").glob("*.yaml"))
    text = edited.read_text(encoding="utf-8")
    edited.write_text(re.sub(r"\n  base: [0-9a-f]{40}", "\n  base: " + "f" * 40, text, count=1), encoding="utf-8")
    runs = _runs(1)
    runs[0]["receipt"]["case_ids"] = [c.id for c in committed]
    runs[0]["cases_digest"] = cases_digest(committed)
    runs[0]["environment"]["git_sha"] = sha
    local = load_cases(tmp_path / "repo")
    assert cases_digest(local) != runs[0]["cases_digest"]
    got, source = R.cases_for(runs, local)
    assert source == f"case files at git {sha}" and cases_digest(got) == runs[0]["cases_digest"]
    runs[0]["environment"]["git_sha"] = "0" * 40
    assert R.cases_for(runs, local) == (local, "local case files")


def test_soh_repo_report_reads_the_store(store_run, tmp_path, capsys):
    import json

    from evals.core import cases_digest
    from harness import cli
    import yaml

    from evals.core import load_cases
    from harness import memory_store as ms
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    for c in _repo_cases():
        raw = {"id": c.id, "modality": c.modality, "prompt": c.prompt, "params": c.params}
        (pilot / f"{c.id}.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    cases = load_cases(pilot)
    receipt = {"case_ids": [c.id for c in cases], "repeat": 1, "max_tokens": 32768}
    conn = ms.connect(tmp_path / "s.db")
    rows = {466: [], 467: []}
    for r in _pilot_rows():
        rows[r["run_id"]].append({k: r[k] for k in ("candidate", "case_id", "passed", "failure_class")})
    ids = [store_run(f"run-{n}", "repo", rows=rows[n], cases_digest=cases_digest(cases), conn=conn,
                     receipt=receipt) for n in (466, 467)]
    conn.close()
    assert cli.main(["repo-report", "--json", *map(str, ids), "--store", str(tmp_path / "s.db"),
                     "--cases", str(pilot), "--resamples", "200"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["ok"] and got["views"]["limits as losses"]["p"] == 0.0625
    assert cli.main(["repo-report", str(ids[0]), "--store", str(tmp_path / "s.db"), "--cases", str(pilot)]) == 1


def test_there_is_one_wilson():
    from evals import claims_report
    from harness import intervals
    assert claims_report.wilson is intervals.wilson


def test_an_empty_fair_subset_reports_beside_the_valid_set():
    rep = R.report(_runs(466, 467), _pilot_rows(), _repo_cases(), resamples=50, fair=set())
    assert rep["fair"]["views"]["limits as losses"]["cases"] == 0
    assert "fair subset: 0 cases from 0 tasks" in R.text(rep)


def test_a_case_the_receipt_validated_as_not_valid_is_set_aside():
    runs = _runs(466, 467)
    for r in runs:
        r["receipt"]["validation"] = {"sohot-371-spec": "flaky: x"}
    rep = R.report(runs, _pilot_rows(), _repo_cases(), resamples=50)
    assert rep["set_aside"]["not_valid"] == ["sohot-371-spec"]
    assert rep["views"]["limits as losses"]["cases"] == 35


def _arms(sent_a, sent_b, server=None):
    runs = _runs(472, 474)
    for r, sent in zip(runs, (sent_a, sent_b)):
        r["receipt"]["requests"] = {ORNITH: sent}
        r["receipt"]["server_sampling"] = {ORNITH: server or {}}
    rows = []
    for t in range(8):
        for v in R.VARIANTS:
            rows += [_row(472, ORNITH, f"t{t}-{v}", "I"), _row(474, ORNITH, f"t{t}-{v}", "P" if t < 7 else "I")]
    cases = [_case(f"t{t}-{v}", f"{t:040x}", v) for t in range(8) for v in R.VARIANTS]
    return R.report(runs, rows, cases, resamples=50, fair=set())


def test_two_runs_of_one_spec_with_different_settings_are_two_sides():
    a = [{"max_tokens": 32768, "sampling": {"temperature": 0.2}, "template": {}, "system_sha": "s"}]
    b = [{"max_tokens": m, "sampling": {"temperature": 1.0, "top_k": 20}, "template": {"enable_thinking": True},
          "system_sha": "s"} for m in (32768, 65536)]
    rep = _arms(a, b, server={"top_k": 20, "min_p": 0.05000000074505806})
    base, cand = rep["baseline"], rep["candidate"]
    assert base != cand and {rep["sides"][base]["run"], rep["sides"][cand]["run"]} == {472, 474}
    v = _losses(rep)
    assert (v["rates"][base]["all"]["resolved"], v["rates"][cand]["all"]["resolved"]) == (0, 14)
    assert (v["rates"][base]["all"]["n"], v["rates"][cand]["all"]["n"]) == (16, 16)
    assert len(v["only"][cand]) == 7 and v["verdict"] == "differs"
    assert rep["sides"][base]["label"] == "run 472: max_tokens 32768, temperature=0.2, top_k default (server 20), enable_thinking default"
    assert rep["sides"][cand]["label"] == ("run 474: max_tokens 32768/65536, temperature=1.0, top_k=20, "
                                           "enable_thinking=True")
    assert rep["sides"][cand]["label"] in R.text(rep) and "\n  run 474 " in R.text(rep)


def test_two_runs_of_one_spec_with_identical_settings_still_pair_by_run():
    same = [{"max_tokens": 32768, "sampling": {"temperature": 0.2}, "template": {}, "system_sha": "s"}]
    rep = _arms(same, same)
    assert rep["sides"][rep["baseline"]]["label"] == "run 472: same settings sent"
    assert _losses(rep)["rates"][rep["candidate"]]["all"]["n"] == 16


def test_a_legacy_receipt_reads_its_settings_from_the_lane_fields():
    runs = _runs(466)
    runs[0]["receipt"].update(max_tokens=32768, sampling={"repo": {"temperature": 0.2}}, budget_ladder=[])
    assert R.sent(runs[0], ORNITH) == {"max_tokens": [32768], "temperature": 0.2}
    runs[0]["receipt"].update(budget_ladder=[32768, 65536], template={"repo": {"enable_thinking": False}})
    assert R.sent(runs[0], ORNITH) == {"max_tokens": [32768, 65536], "temperature": 0.2, "enable_thinking": False}
    runs[0]["receipt"]["requests"] = {ORNITH: [{"max_tokens": 4000, "sampling": {"temperature": 0.2}},
                                               {"max_tokens": 8000, "sampling": {"temperature": 0.6}}]}
    assert R.sent(runs[0], ORNITH) == {"max_tokens": [4000, 8000], "temperature": "0.2/0.6"}


def test_a_two_run_report_refuses_a_run_holding_two_candidates():
    rows = [_row(1, BASE, "t0-spec", "P"), _row(1, CAND, "t0-spec", "P"), _row(2, CAND, "t0-spec", "P")]
    with pytest.raises(R.Refused, match="run 1 holds 2 candidates"):
        R.report(_runs(1, 2), rows, [_case("t0-spec", "0" * 40, "spec")], resamples=50, fair=set())
