"""Generating the decide lane's cases from human-labelled public benchmarks. #423.

    uv run python -m evals.decide_corpus [--out evals/cases/decide]

Record ids come from bespokelabsai/nimble's published public-benchmark subset
manifests at NIMBLE_REV (ids only; the nimble repository states no license).
The text and labels come from each upstream dataset, under its own license,
recorded in every case. The field wording is this repo's own.

Four families, six cases each: route (MASSIVE), check (SQuAD 2.0), policy
(Civil Comments) and rate (HelpSteer2). Selection walks each manifest in order
and is label-aware only where stated, so a constant answer cannot pass a field.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tarfile
from pathlib import Path

import yaml

NIMBLE = "bespokelabsai/nimble"
#: Must equal NIMBLE_REV in scripts/versions.sh; a test holds them together.
NIMBLE_REV = "dcfdbd9a64f0d869f658d7a72f1beaee32737773"
MANIFESTS = "docs/assets/public-benchmarks/subsets"
DEFAULT_OUT = Path(__file__).resolve().parent / "cases" / "decide"
PER_FAMILY = 6
ROWS_API = "https://datasets-server.huggingface.co/rows"

MASSIVE_URL = ("https://amazon-massive-nlu-dataset.s3.amazonaws.com/"
               "amazon-massive-dataset-1.1.tar.gz")
#: The archive nimble's manifest records reading, checked before use.
MASSIVE_SHA256 = "4cba5faa11c71437928e17cb1b9b3d8b8e727e7ea363a3a9a8045e19c0491577"
SQUAD_URL = "https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v2.0.json"

SOURCES = {
    "massive": {"dataset": "MASSIVE 1.1 (AmazonScience), test partition, en-US",
                "url": "https://huggingface.co/datasets/AmazonScience/massive",
                "license": "CC BY 4.0", "manifest": "massive-en-US-manifest.json"},
    "squad2": {"dataset": "SQuAD 2.0, dev (Rajpurkar et al. 2018)",
               "url": "https://rajpurkar.github.io/SQuAD-explorer/",
               "license": "CC BY-SA 4.0", "manifest": "squad2-manifest.json"},
    "civil_comments": {"dataset": "Civil Comments (google/civil_comments), test",
                       "url": "https://huggingface.co/datasets/google/civil_comments",
                       "license": "CC0 1.0", "manifest": "civil_comments-manifest.json"},
    "helpsteer2": {"dataset": "HelpSteer2 (nvidia/HelpSteer2), validation",
                   "url": "https://huggingface.co/datasets/nvidia/HelpSteer2",
                   "license": "CC BY 4.0", "manifest": "helpsteer2-manifest.json"},
}

# ---- route: MASSIVE --------------------------------------------------------

SCENARIOS = {
    "alarm": "setting, changing or removing alarms",
    "audio": "device volume and audio output",
    "calendar": "events, reminders and the user's schedule",
    "cooking": "recipes and cooking instructions",
    "datetime": "the current date, time or time zones",
    "email": "reading, writing or managing email",
    "general": "chit-chat, jokes and requests no other domain covers",
    "iot": "smart-home devices: lights, plugs, vacuums, coffee machines",
    "lists": "to-do and shopping lists",
    "music": "music preferences and facts about music",
    "news": "news headlines and stories",
    "play": "playing music, podcasts, radio, audiobooks or games",
    "qa": "factual questions, definitions, maths and currency",
    "recommendation": "suggestions for places, events or things to do",
    "social": "posting to or reading social media",
    "takeaway": "ordering food for delivery or pickup",
    "transport": "tickets, taxis, trains and traffic",
    "weather": "weather conditions and forecasts",
}
SLOT_FIELDS = {
    "mentions_time": ({"date", "time", "timeofday", "time_zone", "general_frequency"},
                      "Does the request mention a date, a time, a time of day or a recurrence?"),
    "mentions_person": ({"person", "relation"},
                        "Does the request name or refer to a specific person or relative?"),
    "mentions_place": ({"place_name", "business_name"},
                       "Does the request name a specific place or business?"),
    "mentions_media": ({"media_type", "artist_name", "song_name", "radio_name", "game_name",
                        "audiobook_name", "podcast_name", "podcast_descriptor",
                        "playlist_name", "music_genre", "movie_name", "music_album"},
                       "Does the request name a song, artist, genre, playlist, station, "
                       "podcast, audiobook, game, film or kind of media?"),
}
_SLOT = re.compile(r"\[([a-z_]+) :")


def route_schema() -> dict:
    schema = {"domain": {"type": "enum", "choices": list(SCENARIOS),
                         "description": "Which assistant domain should handle this request?",
                         "choice_descriptions": dict(SCENARIOS)}}
    for name, (_, question) in SLOT_FIELDS.items():
        schema[name] = {"type": "boolean", "description": question}
    return schema


def route_answers(row: dict) -> dict:
    slots = set(_SLOT.findall(row["annot_utt"]))
    out = {"domain": row["scenario"]}
    for name, (kinds, _) in SLOT_FIELDS.items():
        out[name] = bool(slots & kinds)
    return out


def pick_route(ids: list[str], rows: dict[str, dict], n: int = PER_FAMILY) -> list[str]:
    """Manifest order, distinct domains, first covering a positive per boolean."""
    order = [i for i in ids if i in rows]
    chosen, domains = [], set()
    for name in SLOT_FIELDS:
        for i in order:
            row = rows[i]
            if i not in chosen and row["scenario"] not in domains \
                    and route_answers(row)[name]:
                chosen.append(i)
                domains.add(row["scenario"])
                break
    for i in order:
        if len(chosen) >= n:
            break
        if i not in chosen and rows[i]["scenario"] not in domains:
            chosen.append(i)
            domains.add(rows[i]["scenario"])
    return chosen[:n]


def route_case(row: dict) -> dict:
    return {"id": f"route-massive-{row['id']}",
            "prompt": "Route this voice-assistant request and say what it mentions.",
            "context": row["utt"], "schema": route_schema(),
            "answers": route_answers(row), "source": "massive",
            "record": f"massive-{row['id']}",
            "label": "scenario; booleans from the human slot annotation (annot_utt)"}

# ---- check: SQuAD 2.0 ------------------------------------------------------

QUESTIONS = 5


def pick_check(ids: list[str], questions: dict[str, dict], n: int = PER_FAMILY) -> list[list[str]]:
    """Paragraphs in manifest order whose first five questions mix both answers."""
    groups: dict[str, list[str]] = {}
    for i in ids:
        q = questions.get(i)
        if q:
            groups.setdefault(q["context"], []).append(i)
    out = []
    for group in groups.values():
        head = group[:QUESTIONS]
        answerable = sum(1 for i in head if questions[i]["answerable"])
        if len(head) == QUESTIONS and 0 < answerable < QUESTIONS:
            out.append(head)
        if len(out) == n:
            break
    return out


def check_case(group: list[str], questions: dict[str, dict]) -> dict:
    import hashlib
    first = questions[group[0]]
    schema, answers = {}, {}
    # SQuAD lists answerable questions first; a hash order keeps position uninformative.
    shuffled = sorted(group, key=lambda q: hashlib.sha256(q.encode()).hexdigest())
    for k, qid in enumerate(shuffled, 1):
        q = questions[qid]
        schema[f"q{k}"] = {"type": "boolean", "description": (
            f"True only if the paragraph itself states the answer to: {q['question']}")}
        answers[f"q{k}"] = q["answerable"]
    return {"id": f"check-{group[0]}",
            "prompt": "Check which of these questions the paragraph answers.",
            "context": first["context"], "schema": schema, "answers": answers,
            "source": "squad2", "record": ", ".join(group),
            "label": "answerable when the human answer list is non-empty"}

# ---- policy: Civil Comments -------------------------------------------------

THRESHOLD = 0.5
POLICY = {
    "toxic": ("toxicity", "Is the comment rude, disrespectful or unreasonable enough "
                          "that a reader would likely leave the discussion?"),
    "insult": ("insult", "Does the comment insult or demean a person or group?"),
    "obscene": ("obscene", "Does the comment contain obscene or vulgar language?"),
    "threat": ("threat", "Does the comment threaten or wish harm on anyone?"),
    "identity_attack": ("identity_attack", "Does the comment attack people for an identity "
                                           "such as race, religion, gender or sexuality?"),
}


def policy_answers(row: dict) -> dict:
    return {name: float(row[attr]) >= THRESHOLD for name, (attr, _) in POLICY.items()}


def pick_policy(ids: list[str], rows: dict[str, dict], n: int = PER_FAMILY) -> list[str]:
    """Manifest order: half above the toxicity threshold, half below; the toxic
    half takes the first positive for each other attribute before filling."""
    want = n // 2
    toxic = [i for i in ids if i in rows and policy_answers(rows[i])["toxic"]]
    hot: list[str] = []
    for name in POLICY:
        got = next((i for i in toxic if i not in hot and policy_answers(rows[i])[name]), None)
        if got and len(hot) < want:
            hot.append(got)
    hot += [i for i in toxic if i not in hot][:want - len(hot)]
    cold = [i for i in ids if i in rows and not policy_answers(rows[i])["toxic"]][:n - want]
    return [i for i in ids if i in hot or i in cold]


def policy_case(rid: str, row: dict) -> dict:
    schema = {name: {"type": "boolean", "description": question}
              for name, (_, question) in POLICY.items()}
    return {"id": f"policy-{rid.replace('_', '-')}",
            "prompt": "Apply the moderation policy below to this comment.",
            "context": row["text"].strip(), "schema": schema,
            "answers": policy_answers(row), "source": "civil_comments", "record": rid,
            "label": f"rater fraction >= {THRESHOLD} per attribute"}

# ---- rate: HelpSteer2 -------------------------------------------------------

RUBRIC = {
    "helpfulness": "How useful is the response to the prompt overall?",
    "correctness": "How correct and complete are the facts in the response?",
    "coherence": "How consistent and clearly expressed is the response?",
    "complexity": "How much expertise would writing the response require?",
    "verbosity": "How long and detailed is the response relative to what was asked?",
}
LEVELS = {"0": "lowest", "1": "low", "2": "middle", "3": "high", "4": "highest"}
MAX_CHARS = 3000


def pick_rate(ids: list[str], rows: dict[str, dict], n: int = PER_FAMILY) -> list[str]:
    """Manifest order, single-turn, short enough to read, one response per prompt."""
    out, prompts = [], set()
    for i in ids:
        row = rows.get(i)
        if not row or "<extra_id_1>" in row["prompt"] or row["prompt"] in prompts:
            continue
        if len(row["prompt"]) + len(row["response"]) > MAX_CHARS:
            continue
        out.append(i)
        prompts.add(row["prompt"])
        if len(out) == n:
            break
    return out


def rate_case(rid: str, row: dict) -> dict:
    schema = {name: {"type": "enum", "choices": list(LEVELS), "description":
                     f"{question} Rate on a 0-4 scale.",
                     "choice_descriptions": dict(LEVELS)}
              for name, question in RUBRIC.items()}
    return {"id": f"rate-{rid}",
            "prompt": "Rate the assistant response to the prompt on each attribute.",
            "context": f"PROMPT:\n{row['prompt'].strip()}\n\nRESPONSE:\n{row['response'].strip()}",
            "schema": schema, "answers": {k: str(int(row[k])) for k in RUBRIC},
            "source": "helpsteer2", "record": rid,
            "label": "the annotators' 0-4 scores as published"}

# ---- writing ---------------------------------------------------------------


def case_yaml(case: dict) -> str:
    src = SOURCES[case["source"]]
    body = {
        "id": case["id"], "modality": "decide", "prompt": case["prompt"],
        "context": case["context"], "params": {"schema": case["schema"]},
        "assert": {"answers": case["answers"]},
        "attribution": {
            "dataset": src["dataset"], "url": src["url"], "license": src["license"],
            "record": case["record"], "label": case["label"],
            "selected_from": f"{NIMBLE}@{NIMBLE_REV}:{MANIFESTS}/{src['manifest']}",
        },
    }
    header = (f"# {src['dataset']}, {src['license']} ({src['url']}).\n"
              f"# Generated by evals/decide_corpus.py; edit the generator, not this file.\n")
    return header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100)


def write_cases(cases: list[dict], out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.yaml"):
        old.unlink()
    written = []
    for case in cases:
        path = out / f"{case['id']}.yaml"
        path.write_text(case_yaml(case), encoding="utf-8")
        written.append(path)
    return written

# ---- fetching (network; not exercised by the tests) -------------------------


def _get(url: str, **params):
    import time

    import httpx
    for attempt in range(8):
        r = httpx.get(url, params=params or None, timeout=120, follow_redirects=True)
        if r.status_code != 429 and r.status_code < 500:
            break
        # The rows API rate-limits a few hundred single-row reads, and 502s.
        time.sleep(float(r.headers.get("retry-after") or 2 ** attempt))
    r.raise_for_status()
    return r


def manifest_ids(name: str) -> list[str]:
    url = f"https://raw.githubusercontent.com/{NIMBLE}/{NIMBLE_REV}/{MANIFESTS}/{name}"
    return list(_get(url).json()["ids"])


def hf_row(dataset: str, config: str, split: str, index: int) -> dict:
    got = _get(ROWS_API, dataset=dataset, config=config, split=split,
               offset=index, length=1).json()["rows"]
    if not got or got[0]["row_idx"] != index:
        raise SystemExit(f"{dataset} {split} has no row {index}")
    return got[0]["row"]


def massive_rows() -> dict[str, dict]:
    import hashlib
    blob = _get(MASSIVE_URL).content
    digest = hashlib.sha256(blob).hexdigest()
    if digest != MASSIVE_SHA256:
        raise SystemExit(f"MASSIVE archive changed: sha256 {digest}")
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        member = tar.extractfile("1.1/data/en-US.jsonl")
        lines = member.read().decode("utf-8").splitlines()
    rows = (json.loads(line) for line in lines if line.strip())
    return {f"massive-{r['id']}": r for r in rows if r["partition"] == "test"}


def squad_questions() -> dict[str, dict]:
    out = {}
    for article in _get(SQUAD_URL).json()["data"]:
        for para in article["paragraphs"]:
            for qa in para["qas"]:
                out[f"squad2-{qa['id']}"] = {
                    "context": para["context"], "question": qa["question"],
                    "answerable": bool(qa["answers"]) and not qa.get("is_impossible")}
    return out


def _indexed(ids: list[str], dataset: str, config: str, split: str,
             enough, limit: int = 120) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for rid in ids[:limit]:
        rows[rid] = hf_row(dataset, config, split, int(rid.rsplit("-", 1)[1]))
        if enough(rows):
            break
    return rows


def build() -> list[dict]:
    cases = []
    ids = manifest_ids(SOURCES["massive"]["manifest"])
    rows = massive_rows()
    cases += [route_case(rows[i]) for i in pick_route(ids, rows)]

    ids = manifest_ids(SOURCES["squad2"]["manifest"])
    questions = squad_questions()
    cases += [check_case(g, questions) for g in pick_check(ids, questions)]

    ids = manifest_ids(SOURCES["civil_comments"]["manifest"])
    rows = _indexed(ids, "google/civil_comments", "default", "test",
                    lambda got: False, limit=len(ids))
    cases += [policy_case(i, rows[i]) for i in pick_policy(ids, rows)]

    ids = manifest_ids(SOURCES["helpsteer2"]["manifest"])
    rows = _indexed(ids, "nvidia/HelpSteer2", "default", "validation",
                    lambda got: len(pick_rate(ids, got)) >= PER_FAMILY, limit=len(ids))
    cases += [rate_case(i, rows[i]) for i in pick_rate(ids, rows)]
    return cases


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default=str(DEFAULT_OUT))
    args = p.parse_args(argv)
    cases = build()
    written = write_cases(cases, Path(args.out))
    print(f"{len(written)} decide cases in {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
