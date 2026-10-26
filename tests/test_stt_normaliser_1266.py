"""The English WER normaliser scores a pair: compounds, spellings, digit years, elisions and fillers are not errors; a wrong word is (#1266)."""
import pytest

from harness.checks import speech


@pytest.mark.parametrize("reference, heard", [
    ("TO DAY I SHOUTED", "Today, I shouted."),
    ("TO MORROW IS THE EXAMINATION", "Tomorrow is the examination."),
    ("WE'VE TORTURED EACH OTHER ENOUGH FOR TONIGHT", "We've tortured each other enough for to night."),
    ("MAINHALL LIKED ALEXANDER BECAUSE HE WAS AN ENGINEER", "Main Hall liked Alexander because he was an engineer."),
    ("THE TOP FLOOR BELONGS TO MILES MC LAREN", "The top floor belongs to Miles McLaren."),
    ("ALSO THE PENCIL CUTTINGS GOOD BYE", "also the pencil cuttings. Goodbye."),
    ("WE WON'T TALK ABOUT HER ANY MORE", "We won't talk about her anymore"),
    ("LIKE THE DOVES VOICE", "like the dove's voice"),
    ("NONE TO CHERISH THEE WITH MOTHERS SMILES", "none to cherish thee with mother's smiles"),
    ("I CANNOT SAY", "I can't say"),
])
def test_split_and_joined_compounds_score_no_error(reference, heard):
    assert speech.wer_counts(reference, heard)[0] == 0


@pytest.mark.parametrize("reference, heard", [
    ("ON AUGUST TWENTY SEVENTH EIGHTEEN THIRTY SEVEN SHE WRITES", "On August 27, 1837, she writes,"),
    ("JANUARY AND FEBRUARY OF EIGHTEEN THIRTY SEVEN HAD PASSED AWAY", "January and February of 1837 had passed away"),
    ("IN NINETEEN OH FIVE", "in 1905"),
    ("IN EIGHTEEN HUNDRED", "in 1800"),
    ("ONE THOUSAND EIGHT HUNDRED THIRTY SEVEN MEN", "1837 men"),
])
def test_a_year_written_as_digits_matches_its_spoken_reference(reference, heard):
    assert speech.wer_counts(reference, heard)[0] == 0


@pytest.mark.parametrize("reference, heard", [
    ("We shipped 6319 crates.", "we shipped sixty three nineteen crates"),
    ("He walked 1019 miles.", "he walked ten nineteen miles"),
    ("It was the 27 of them.", "it was the twenty seventh of them"),
])
def test_a_tts_count_read_year_style_is_still_an_error(reference, heard):
    assert speech.wer_counts(reference, heard)[0] > 0


@pytest.mark.parametrize("reference, heard, errors", [
    ("HEDGE A FENCE", "Hedge offense.", 2),
    ("YOU KNOW CAPTAIN LAKE", "You know Captain Leak.", 1),
    ("SAID LORD CHELFORD ADDRESSING ME", "said Lord Shelford addressing me", 1),
    ("BUT WE'RE NOT ER EXACTLY WELCOMED", "but we're not uh exactly welcome.", 1),
    ("CAPTAIN SERVADAC HASTENED TOWARDS HIM", "Captain Servadac hastened toward him.", 1),
    ("IN EIGHTEEN THIRTY SEVEN", "in 1838", 1),
    ("TO DAY I SHOUTED", "Tuesday I shouted", 2),
    ("THE CAT SAT", "the cats at", 2),
    ("GONE AWAY A WHEY", "gone away a way", 1),
    ("A MONTFICHET A MONTFICHET", "Amont Vichy, amont Vichy", 4),
])
def test_a_genuinely_wrong_word_still_counts(reference, heard, errors):
    assert speech.wer_counts(reference, heard)[0] == errors


@pytest.mark.parametrize("reference, heard", [
    ("ENTER HAMLET WITH HIS FAVOURITE BOAR HOUND", "Enter Hamlet with his favorite boarhound,"),
    ("STUFF IT INTO YOU HIS BELLY COUNSELLED HIM", "Stuff it into you, his belly counseled him."),
    ("THE SOMBRE OLD TREES", "the somber old trees"),
    ("ENQUIRED ROBIN", "Inquired Robin"),
    ("WHY A TONGUE IMPRESS'D WITH HONEY", "Why a tongue impressed with honey"),
    ("SHE CEASD AND SMILD IN TEARS", "She ceased and smiled in tears"),
    ("BUT WE'RE NOT ER EXACTLY", "but we are not uh, exactly"),
    ("O LORD UM HMM", "Oh Lord."),
    ("THERE'S NO FEAR", "there is no fear"),
])
def test_british_spellings_and_fillers_score_no_error(reference, heard):
    assert speech.wer_counts(reference, heard)[0] == 0


def test_wer_and_wer_counts_score_the_pair_alike():
    ref, heard = "TO DAY I SHOUTED AT CAPTAIN LAKE", "Today I shouted at Captain Leak"
    errors, words = speech.wer_counts(ref, heard)
    assert (errors, words) == (1, 6)
    assert speech.wer(ref, heard) == pytest.approx(errors / words)


def test_runs_scored_under_two_normaliser_versions_are_not_comparable():
    from evals.core import Receipt, comparable
    base = dict(case_ids=("x",), repeat=1, sampling={}, gateway="http://gw")
    new = Receipt(modality="stt", instruments={"wer": speech.NORMALISER}, **base)
    old = Receipt(modality="stt", instruments={}, **base)
    ok, why = comparable(new, old)
    assert not ok and "normaliser" in why
    assert comparable(new, Receipt(modality="stt", instruments={"wer": speech.NORMALISER}, **base))[0]
    assert comparable(Receipt(modality="svg", **base), Receipt(modality="svg", instruments={"wer": "x"}, **base))[0]


def test_a_wer_lane_receipt_records_the_normaliser():
    from evals import run
    assert run.instruments(["stt:mlx-community/parakeet-tdt-0.6b-v2"], "stt")["wer"] == speech.NORMALISER
    assert run.instruments(["tts:mlx-community/Kokoro-82M-bf16"], "tts")["wer"] == speech.NORMALISER
    assert "wer" not in run.instruments([], "code")


def test_soh_floors_says_which_normaliser_scored_each_item(tmp_path):
    import json

    from harness import floors
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "s.db")
    old = conn.execute("INSERT INTO runs (path, lane, recorded_at, receipt) VALUES ('r1', 'tts', 0, '{}')").lastrowid
    new = conn.execute("INSERT INTO runs (path, lane, recorded_at, receipt) VALUES ('r2', 'tts', 0, ?)",
                       (json.dumps({"instruments": {"wer": speech.NORMALISER}}),)).lastrowid
    voice = floors.REFERENCE["tts"]
    rows = [(old, "t1", ""), (new, "t2", ""), (old, "t3", "word error rate 0.5 over the limit; heard 'to day it rained'")]
    for seq, (run, case, detail) in enumerate(rows):
        conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, passed, metrics, detail) "
                     "VALUES (?, ?, ?, ?, 1, ?, ?)",
                     (run, seq, voice, case, json.dumps({"wer": 0.0, "wer_errors": 0, "wer_words": 4}), detail))
    items = floors.tts_items(conn, {"t1": "it rained all day", "t2": "it rained all day", "t3": "Today it rained."})
    assert [(i["case"], i["scored"], i["errors"]) for i in items] == [
        ("t1", "1", 0), ("t2", speech.NORMALISER, 0), ("t3", speech.NORMALISER, 0)]
    conn.close()
