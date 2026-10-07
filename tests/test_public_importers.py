"""Public-reference importers for decide, extract, retrieval and stt, with pinned negative controls. #603."""
import hashlib
from pathlib import Path

import pytest
import yaml

from evals import importers
from evals.core import Case, load_cases, score
from evals.importers import librispeech, squad2, squad2_check, squad2_extract, squad2_retrieval
from harness import holdout

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases"
SQUAD = {"squad2_check": squad2_check, "squad2_extract": squad2_extract,
         "squad2_retrieval": squad2_retrieval}
PROVENANCE = {"dataset", "url", "license", "source", "revision", "item", "date", "transform",
              "importer", "date_note", "trained_on"}
#: A negative control must pass at most this share of what the reference passes.
CEILING = 0.1


def _qa(qid, question, answers=()):
    return {"id": qid, "question": question,
            "answers": [{"text": a, "answer_start": 0} for a in answers],
            "is_impossible": not answers}


def _squad():
    """Two articles, three paragraphs each, every paragraph mixing both kinds of question."""
    data = []
    for t in ("Alpha_river", "Beta_town"):
        paras = []
        for i in range(3):
            ctx = (f"{t} paragraph {i}. The founder was Ada{i} in year 19{i}0. "
                   f"The river is {i + 3} miles long and flows north.")
            qas = [_qa(f"{t}-{i}-a", f"Who founded {t} {i}?", [f"Ada{i}", f"Ada{i}"]),
                   _qa(f"{t}-{i}-b", f"When was {t} {i} founded?", [f"19{i}0"]),
                   _qa(f"{t}-{i}-c", f"How long is the river {i}?", [f"{i + 3} miles"]),
                   _qa(f"{t}-{i}-d", f"Who closed {t} {i}?"),
                   _qa(f"{t}-{i}-e", f"Why did {t} {i} move?"),
                   _qa(f"{t}-{i}-f", f"Which mayor wrote about {t} {i}?",
                       ["a mayor whose name runs to far too many words"])]
            paras.append({"context": ctx, "qas": qas})
        data.append({"title": t, "paragraphs": paras})
    return {"version": "v2.0", "data": data}


def test_extract_equals_accepts_a_list_of_alternatives():
    case = Case(id="x", modality="extract", prompt="Who?",
                assertions={"equals": ["Normans", "the Normans"]})
    assert score(case, " the normans ").passed
    assert score(case, "Normans").passed
    assert not score(case, "Normans and Franks").passed


# --- squad2: one pinned file, three lanes ----------------------------------------

def test_the_squad_file_is_refused_when_its_bytes_change():
    with pytest.raises(ValueError, match="sha256"):
        squad2.verified(b"not the dev set")


def test_the_squad_url_is_the_pinned_commit():
    assert squad2.REVISION in squad2.URL and len(squad2.REVISION) == 40


def test_paragraphs_carry_the_article_and_answerability():
    first = squad2.paragraphs(_squad())[0]
    assert first.pid == "Alpha_river#0"
    assert [q.answerable for q in first.qas] == [True, True, True, False, False, True]
    assert first.qas[0].answers == ("Ada0",)


def _run(name, tmp_path, rows):
    importers.run(name, root=tmp_path, rows=rows)
    return load_cases(tmp_path / SQUAD[name].LANE / name)


def test_check_cases_mix_both_answers_and_shuffle_question_order(tmp_path):
    cases = _run("squad2_check", tmp_path, squad2_check.select(_squad(), 10))
    assert len(cases) == 6
    for c in cases:
        answers = c.assertions["answers"]
        assert len(answers) == squad2_check.QUESTIONS and 0 < sum(answers.values()) < 5
    assert len({list(c.assertions["answers"].values())[0] for c in cases}) == 2


def test_check_cases_skip_paragraphs_already_in_the_lane():
    rows = squad2_check.select(_squad(), 10, {"squad2-Alpha_river-0-a"})
    assert len(rows) == 5 and "Alpha_river#0" not in {r["pid"] for r in rows}


def test_extract_cases_ask_one_short_answer_each_with_every_gold_spelling(tmp_path):
    cases = _run("squad2_extract", tmp_path, squad2_extract.select(_squad(), 10))
    assert len(cases) == 6
    for c in cases:
        gold = c.assertions["equals"]
        assert gold and all(len(g.split()) <= squad2_extract.MAX_WORDS and g in c.context
                            for g in gold)


def test_retrieval_cases_rank_their_own_article_and_the_corpora_are_written(tmp_path):
    cases = _run("squad2_retrieval", tmp_path, squad2_retrieval.select(_squad(), 4))
    assert len(cases) == 4
    for c in cases:
        ids = [d.split('"')[3] for d in c.input_file.read_text(encoding="utf-8").splitlines()]
        assert c.assertions["relevant"][0] in ids and len(set(ids)) == len(ids)
        assert c.assertions["k"] == squad2_retrieval.K
    assert sorted(p.name for p in (tmp_path / "retrieval" / "squad2_retrieval").glob("*.jsonl")) \
        == ["alpha-river.jsonl", "beta-town.jsonl"]


def test_cases_may_share_a_file_only_with_the_same_bytes(tmp_path):
    def one(cid, data):
        return importers.Imported({"id": cid, "modality": "extract", "prompt": "p"},
                                  files=(("shared.jsonl", data),))
    importers.write(squad2_extract, "s", [one("a", b"x"), one("b", b"x")], tmp_path)
    assert (tmp_path / "extract" / "s" / "shared.jsonl").read_bytes() == b"x"
    with pytest.raises(ValueError, match="differs"):
        importers.write(squad2_extract, "s", [one("a", b"x"), one("b", b"y")], tmp_path)


@pytest.mark.parametrize("name", sorted(SQUAD))
def test_importing_twice_gives_the_same_bytes(name, tmp_path):
    mod = SQUAD[name]
    rows = mod.select(_squad(), 4)
    importers.run(name, root=tmp_path / "a", rows=rows)
    importers.run(name, root=tmp_path / "b", rows=rows)
    a = {p.name: p.read_bytes() for p in (tmp_path / "a" / mod.LANE / name).iterdir()}
    b = {p.name: p.read_bytes() for p in (tmp_path / "b" / mod.LANE / name).iterdir()}
    assert a == b and a


# --- librispeech: a committed manifest, audio fetched into a cache -------------------

def _ls_rows():
    words = "the quick brown fox jumps over a lazy dog again and again".split()
    return [(i, {"id": f"84-121-{i:04d}", "text": " ".join(words[: 3 + i % 9]).upper()})
            for i in range(30)]


def test_librispeech_selection_is_seeded_by_utterance_and_bounded_in_length():
    picked = librispeech.select(_ls_rows(), n=10)
    assert len(picked) == 10
    assert picked == librispeech.select(list(reversed(_ls_rows())), n=10)
    assert all(librispeech.MIN_WORDS <= len(p["text"].split()) <= librispeech.MAX_WORDS
               for p in picked)


def test_librispeech_refuses_audio_whose_bytes_do_not_match_the_manifest(tmp_path):
    entry = {"uid": "84-121-0001", "row": 1, "text": "HELLO THERE FRIEND",
             "sha256": "0" * 64, "bytes": 4}
    with pytest.raises(ValueError, match="sha256"):
        librispeech.download([entry], tmp_path, lambda row: b"flac")
    assert not (tmp_path / "84-121-0001.flac").exists()


def test_librispeech_download_skips_what_the_cache_already_holds(tmp_path):
    blob = b"fLaC-bytes"
    entry = {"uid": "84-121-0001", "row": 1, "text": "HELLO THERE FRIEND",
             "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}
    calls = []
    librispeech.download([entry], tmp_path, lambda row: calls.append(row) or blob)
    librispeech.download([entry], tmp_path, lambda row: calls.append(row) or blob)
    assert calls == [1]


def test_librispeech_reads_the_rows_api_a_page_at_a_time_at_the_pinned_revision(monkeypatch):
    pages, served = [], librispeech.REVISION

    def page(offset, length):
        pages.append(offset)
        return [{"row_idx": i, "row": {"audio": [{"src": f"https://x/--/{served}"
                                                         f"/--/clean/test/{i}/a.flac"}]}}
                for i in range(offset, offset + length)]

    class Reply:
        def __init__(self, url):
            self.content = url.encode()

        def raise_for_status(self):
            return self
    monkeypatch.setattr(librispeech, "_page", page)
    monkeypatch.setattr("httpx.get", lambda url, timeout=None: Reply(url))
    get = librispeech.audio_getter()
    assert b"/test/7/" in get(7) and b"/test/42/" in get(42) and b"/test/150/" in get(150)
    assert pages == [0, 100]
    monkeypatch.setattr(librispeech, "REVISION", "0" * 40)
    with pytest.raises(ValueError, match="revision"):
        librispeech.audio_getter()(3)


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                      site="env:LIBRISPEECH_CACHE")
def test_the_cache_env_var_is_where_fetch_reads_and_points_the_cases(tmp_path, monkeypatch):
    blob = b"fLaC-cached"
    entry = {"uid": "9999-1-0001", "row": 1, "text": "HELLO THERE FRIEND",
             "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}
    (tmp_path / "9999-1-0001.flac").write_bytes(blob)
    monkeypatch.setenv("LIBRISPEECH_CACHE", str(tmp_path))
    monkeypatch.setattr(librispeech, "manifest", lambda: [entry])
    monkeypatch.setattr(librispeech, "audio_getter", lambda: lambda row: pytest.fail("cache was not read"))
    got = librispeech.fetch()
    assert got[0]["audio"] == str((tmp_path / "9999-1-0001.flac").resolve())


def _stt_cases(tmp_path, entries):
    cache = tmp_path / "cache"
    cache.mkdir()
    for e in entries:
        (cache / f"{e['uid']}.flac").write_bytes(b"x")
    importers.run("librispeech", root=tmp_path / "cases", rows=librispeech.rows(entries, cache))
    return load_cases(tmp_path / "cases" / "stt")


def test_librispeech_supersedes_a_generated_case_of_the_same_clip(tmp_path):
    entries = librispeech.manifest()[:3]
    stale = tmp_path / "stt" / f"{entries[0]['uid']}.yaml"
    stale.parent.mkdir(parents=True)
    stale.write_text("id: x\n", encoding="utf-8")
    librispeech.supersede(entries, tmp_path)
    assert not stale.exists()


def test_the_committed_manifest_is_pinned_and_large_enough_for_power(tmp_path):
    entries = librispeech.manifest()
    assert len({e["uid"] for e in entries}) == len(entries) >= librispeech.N
    assert all(len(e["sha256"]) == 64 for e in entries)
    assert sum(e["bytes"] for e in entries) < 60 * 2 ** 20, "keep the download small"
    cases = _stt_cases(tmp_path, entries)
    assert all(c.assertions == {"max_wer": librispeech.MAX_WER} for c in cases)
    assert len(holdout.assign("stt", cases).holdout) >= 130
    got = importers.negative_control(cases, librispeech.RESPONDERS, librispeech.passes)
    assert got["reference"] == (len(cases), len(cases))
    assert got["the"][0] == 0 and got["shuffled"][0] <= CEILING * len(cases)


# --- the committed cases: provenance, size and the pinned negative controls ------------

@pytest.mark.parametrize("name", sorted(SQUAD))
def test_committed_imports_carry_provenance_and_reach_the_holdout(name):
    mod = SQUAD[name]
    files = sorted((CASES / mod.LANE / name).glob("*.yaml"))
    assert files
    for p in files[:: max(1, len(files) // 25)]:
        att = yaml.safe_load(p.read_text(encoding="utf-8"))["attribution"]
        assert PROVENANCE <= set(att), PROVENANCE - set(att)
        assert att["license"] in importers.ALLOWED_LICENSES and att["revision"] == squad2.REVISION
    assert len(holdout.for_lane(mod.LANE).holdout) >= 130


#: (responder, most cases it may pass) per source; the reference must pass every case.
CONTROLS = {"squad2_check": {"all_true": 0, "all_false": 0, "shuffled": 35},
            "squad2_extract": {"unknown": 0, "echo": 0, "shuffled": 0},
            "squad2_retrieval": {"corpus_order": 19, "shuffled": 16}}


@pytest.mark.parametrize("name", sorted(SQUAD))
def test_committed_negative_controls_score_far_under_the_reference(name):
    mod = SQUAD[name]
    cases = load_cases(CASES / mod.LANE / name)
    got = importers.negative_control(cases, mod.RESPONDERS, mod.passes)
    assert got["reference"] == (len(cases), len(cases))
    assert {k: v[0] for k, v in got.items() if k != "reference"} == CONTROLS[name]
    assert all(v <= CEILING * len(cases) for v in CONTROLS[name].values())
