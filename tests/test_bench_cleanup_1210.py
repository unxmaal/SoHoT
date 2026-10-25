"""Benchmarks page: same-size exams say what splits them, older exams fold, descriptions hold only known facts. #1210."""
import re

import pytest

from harness import memory_store as ms
from harness import models, publish, runs, site

ENV = {"hw_model": "Mac17,15", "os": "macOS-27.0.1-arm64", "arch": "arm64", "memory_gb": 96,
       "accelerator": {"kind": "unified", "name": "arm64"}}


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _run(conn, path, when, cands, n=3, digest="d", **receipt):
    rows = [{"case_id": f"c{i}", "candidate": name, "passed": i < passed, "seconds": 1.0}
            for name, passed in cands.items() for i in range(n)]
    base = {"modality": "code", "tier": "measure", "case_ids": [f"c{i}" for i in range(n)],
            "repeat": 1, "cases_digest": digest, "sampling": {"code": {"temperature": 0.2}},
            "max_tokens": 4000}
    runs.record(conn, path, {"generated": when, "receipt": {**base, **receipt},
                             "environment": ENV, "specs": {}, "rows": rows})
    conn.commit()


def _doc(conn):
    mid = conn.execute("SELECT id FROM machines WHERE hw_model = 'Mac17,15'").fetchone()["id"]
    return publish.export(conn, machine_id=mid, now=1.79e9)


def _captions(page: str) -> list[str]:
    return re.findall(r"<h3>(.*?)</h3>", page)


def test_two_exams_on_one_case_set_name_the_field_and_values_that_split_them(conn):
    _run(conn, "runs/a", "2026-10-06T12:00:00", {"q3-4b": 2}, max_tokens=4000)
    _run(conn, "runs/b", "2026-10-06T12:00:00", {"q3-8b": 3}, max_tokens=8000)
    doc = _doc(conn)
    exams = next(l for l in doc["lanes"] if l["lane"] == "code")["exams"]
    assert len(exams) == 2
    assert sorted(e["differs"] for e in exams) == [[["reply budget", "4000 tokens"]],
                                                   [["reply budget", "8000 tokens"]]]
    heads = _captions(site.benchmarks([doc], now=1.79e9))
    assert len(heads) == len(set(heads)) == 2, heads
    assert any("reply budget 4000 tokens" in h for h in heads), heads
    assert any("reply budget 8000 tokens" in h for h in heads), heads


def test_a_sampling_split_names_the_parameter_and_an_unsplit_exam_names_nothing(conn):
    _run(conn, "runs/a", "2026-10-06T12:00:00", {"q3-4b": 2})
    _run(conn, "runs/b", "2026-10-07T12:00:00", {"q3-8b": 3}, sampling={"code": {"temperature": 0.7}})
    _run(conn, "runs/c", "2026-10-08T12:00:00", {"q3-1b": 1}, n=5)
    exams = next(l for l in _doc(conn)["lanes"] if l["lane"] == "code")["exams"]
    by = {e["cases"]: [] for e in exams}
    for e in exams:
        by[e["cases"]].append(e["differs"])
    assert by[5] == [[]]
    assert sorted(by[3]) == [[["temperature", "0.2"]], [["temperature", "0.7"]]]


def test_a_field_only_one_exam_records_does_not_label_a_split_it_did_not_cause(conn):
    _run(conn, "runs/a", "2026-10-06T12:00:00", {"q3-4b": 2}, max_tokens=4000,
         accelerator="unified:arm64")
    _run(conn, "runs/b", "2026-10-06T12:00:00", {"q3-8b": 3}, max_tokens=8000)
    exams = next(l for l in _doc(conn)["lanes"] if l["lane"] == "code")["exams"]
    assert all([k for k, _ in e["differs"]] == ["reply budget"] for e in exams), exams


def test_an_unset_parameter_is_named_only_when_nothing_else_sets_the_exam_apart(conn):
    _run(conn, "runs/a", "2026-10-06T12:00:00", {"q3-4b": 2}, max_tokens=4000)
    _run(conn, "runs/b", "2026-10-07T12:00:00", {"q3-8b": 3}, max_tokens=8000,
         sampling={"code": {"temperature": 0.2, "top_k": 20}})
    _run(conn, "runs/c", "2026-10-08T12:00:00", {"q3-1b": 1}, n=2, digest="d2")
    _run(conn, "runs/d", "2026-10-09T12:00:00", {"q3-2b": 1}, n=2, digest="d2",
         sampling={"code": {"temperature": 0.2, "top_k": 20}})
    exams = next(l for l in _doc(conn)["lanes"] if l["lane"] == "code")["exams"]
    got = sorted(e["differs"] for e in exams)
    assert got == [[["reply budget", "4000 tokens"]],
                   [["reply budget", "8000 tokens"], ["top_k", "20"]],
                   [["top_k", "20"]], [["top_k", "default"]]], got


def test_another_lanes_sampling_alone_neither_splits_an_exam_nor_labels_it(conn):
    _run(conn, "runs/a", "2026-10-06T12:00:00", {"q3-4b": 2}, sampling={"svg": {"temperature": 0.4}})
    _run(conn, "runs/b", "2026-10-07T12:00:00", {"q3-8b": 3}, sampling={})
    exams = next(l for l in _doc(conn)["lanes"] if l["lane"] == "code")["exams"]
    assert len(exams) == 1 and exams[0]["runs"] == 2 and exams[0]["differs"] == []


def test_a_lane_with_three_exams_shows_one_open_and_folds_the_other_two_whole(conn):
    _run(conn, "runs/a", "2026-10-05T12:00:00", {"q3-4b": 1, "old-a": 2}, n=2, digest="d2")
    _run(conn, "runs/b", "2026-10-06T12:00:00", {"q3-4b": 2, "old-b": 3}, n=4, digest="d4")
    _run(conn, "runs/c", "2026-10-07T12:00:00", {"q3-4b": 3, "new-c": 1}, n=5, digest="d5")
    doc = _doc(conn)
    exams = next(l for l in doc["lanes"] if l["lane"] == "code")["exams"]
    assert [e["cases"] for e in exams] == [5, 4, 2]
    page = site.benchmarks([doc], now=1.79e9)
    assert page.count("<details") == 1
    head, _, fold = page.partition("<details")
    fold, _, after = fold.partition("</details>")
    assert "Earlier exams (2)" in fold
    assert "<details open" not in page
    assert head.count("<table>") == 1 and "new-c" in head and "old-b" not in head
    assert fold.count("<table>") == 2
    assert fold.index("4 cases") < fold.index("2 cases"), "newest first inside the fold"
    for e in exams[1:]:
        for r in e["rows"]:
            assert r["candidate"] in fold, r["candidate"]
    rows = lambda html: len(re.findall(r"<tr[^>]*><td>", html))
    assert rows(fold) == sum(len(e["rows"]) for e in exams[1:])
    assert "<table>" not in after


def test_a_lane_with_one_exam_has_no_fold(conn):
    _run(conn, "runs/a", "2026-10-05T12:00:00", {"q3-4b": 1})
    assert "<details" not in site.benchmarks([_doc(conn)], now=1.79e9)


def test_a_model_with_nothing_known_has_no_description_line(conn):
    assert models.about_text(models.about(conn, "")) == ""
    assert models.about_text(models.about(conn, "osocr:auto")) == ""
    assert models.about_text({}) == ""


def test_the_line_prints_only_known_facts_in_order():
    facts = {"family": models.UNKNOWN_FACT, "params": "35B (3B active)", "quant": "Q4_K_M",
             "publisher": "ornith-ai", "source": "https://example.org/x"}
    assert models.about_text(facts) == "35B (3B active) params, Q4_K_M, by ornith-ai"
    assert models.about_text({**facts, "params": models.UNKNOWN_FACT, "quant": models.UNKNOWN_FACT}) == "by ornith-ai"
    assert models.about_text({"family": "llama", "params": "2B"}) == "family llama, 2B params"


@pytest.mark.parametrize("key", ["mflux/dev-q8", "diffusers/prxpixel-t2i", "hf-ocr/PaddleOCR-VL-1.6",
                                 "bm25/okapi", "plan/q3-4b", "best-of-3/q3-4b",
                                 "trace/mflux/dev-q8", "h3/minimax-h3"])
def test_an_engine_or_method_prefix_is_never_the_publisher(conn, key):
    got = models.about(conn, key)
    head = key.split("/")[0]
    assert got["publisher"] != head
    assert f"by {head}" not in models.about_text(got)


def test_mflux_dev_q8_says_nothing_rather_than_by_mflux(conn):
    assert "by mflux" not in models.about_text(models.about(conn, "mflux/dev-q8"))


def test_a_row_with_no_description_renders_no_about_line_and_stale_unknowns_are_dropped():
    bare = publish.model_html({"candidate": "osocr/auto", "model": "osocr/auto", "about": ""})
    assert 'class="about"' not in bare
    old = publish.model_html({"candidate": "x/y", "model": "x/y",
                              "about": "family unknown, 4B params, unknown, by unknown"})
    assert "unknown" not in old and "4B params" in old
    linked = publish.model_html({"candidate": "x/y", "model": "x/y", "about": "", "source": "https://e.org/x"})
    assert "unknown" not in linked and 'href="https://e.org/x"' in linked
