"""Benchmark discovery: sweep registries for newer yardsticks per lane, and judge their freshness. #491, #470."""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import asdict, dataclass

from harness import feeds

HF_DATASETS = "https://huggingface.co/api/datasets"
HF_MODELS = "https://huggingface.co/api/models"
GH_SEARCH = "https://api.github.com/search/repositories"
KIND = "benchmarks"
REGISTRIES = ("huggingface", "github")
#: An entry below both floors is somebody's upload, not a benchmark people use.
MIN_DOWNLOADS = 100
MIN_LIKES = 10
HF_LIMIT = 50
#: Newest first finds what is fresh; most liked finds the canonical source the fresh ones copy.
HF_SORTS = ("createdAt", "likes")
GH_LIMIT = 30

#: Per lane: HF searches (each a params dict) and one GitHub query.
LANE_QUERIES: dict[str, dict] = {
    "code": {"hf": [{"search": "humaneval"}, {"search": "mbpp"}, {"search": "livecodebench"},
                    {"search": "bigcodebench"}, {"search": "code benchmark"},
                    {"search": "code-eval"}],
             "gh": "code generation benchmark python tests"},
    "decide": {"hf": [{"search": "bench", "filter": "task_categories:text-classification"},
                      {"search": "eval", "filter": "task_categories:text-classification"},
                      {"search": "bench", "filter": "task_categories:question-answering"}],
               "gh": "classification benchmark llm labelled"},
    "extract": {"hf": [{"search": "extraction bench"}, {"search": "log parsing"},
                       {"search": "bench", "filter": "task_categories:token-classification"}],
                "gh": "information extraction benchmark llm"},
    "svg": {"hf": [{"search": "svg bench"}, {"search": "svg eval"}, {"search": "text-to-svg"}],
            "gh": "svg generation benchmark llm"},
    "web": {"hf": [{"search": "webdev bench"}, {"search": "html bench"},
                   {"search": "web generation"}],
            "gh": "web page generation benchmark llm"},
    "image": {"hf": [{"search": "bench", "filter": "task_categories:text-to-image"},
                     {"search": "geneval"}],
              "gh": "text-to-image benchmark prompts"},
    "tts": {"hf": [{"search": "bench", "filter": "task_categories:text-to-speech"},
                   {"search": "tts eval"}],
            "gh": "text-to-speech benchmark evaluation"},
}


@dataclass
class Benchmark:
    name: str
    registry: str
    lane: str
    url: str = ""
    license: str = ""
    gated: str = ""
    created: str = ""
    updated: str = ""
    size: str = ""
    rows: int = 0
    task_format: str = ""
    revision: str = ""
    likes: int = 0
    downloads: int = 0
    description: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _tag(tags, prefix: str) -> str:
    return next((t.split(":", 1)[1] for t in tags or () if t.startswith(prefix + ":")), "")


def task_format(features) -> str:
    """The shape of an item, from its column names; '' when no converter could read it."""
    cols = {str(f).lower() for f in features or ()}
    if {"new_problem", "new_solution", "test_code"} <= cols:
        return "self-invoking-python"
    if "test_list" in cols:
        return "assert-list-python"
    if "choices" in cols:
        return "multiple-choice"
    if "label" in cols and cols & {"text", "content", "sentence", "comment", "question"}:
        return "labelled-text"
    return ""


def _features(entry: dict) -> list[str]:
    info = (entry.get("cardData") or {}).get("dataset_info") or {}
    if isinstance(info, list):
        info = info[0] if info else {}
    return [f.get("name", "") for f in info.get("features") or [] if isinstance(f, dict)]


def _rows(entry: dict) -> int:
    info = (entry.get("cardData") or {}).get("dataset_info") or {}
    if isinstance(info, list):
        info = info[0] if info else {}
    return sum(int(s.get("num_examples") or 0) for s in info.get("splits") or [])


def from_hf(entry: dict, lane: str) -> Benchmark:
    repo = entry.get("id") or ""
    tags = entry.get("tags") or []
    gated = entry.get("gated")
    lic = (entry.get("cardData") or {}).get("license") or _tag(tags, "license")
    return Benchmark(
        name=f"hf:{repo}", registry="huggingface", lane=lane,
        url=f"https://huggingface.co/datasets/{repo}",
        license=str(lic if not isinstance(lic, list) else ",".join(lic)),
        gated="" if gated in (False, None, "false") else str(gated),
        created=(entry.get("createdAt") or "")[:10],
        updated=(entry.get("lastModified") or "")[:10],
        size=_tag(tags, "size_categories"), rows=_rows(entry),
        task_format=task_format(_features(entry)), revision=entry.get("sha") or "",
        likes=int(entry.get("likes") or 0), downloads=int(entry.get("downloads") or 0),
        description=" ".join((entry.get("description") or "").split())[:300])


def from_github(item: dict, lane: str) -> Benchmark:
    lic = item.get("license") or {}
    spdx = lic.get("spdx_id") or ""
    return Benchmark(
        name=f"gh:{item.get('full_name', '')}", registry="github", lane=lane,
        url=item.get("html_url") or "",
        license="other" if spdx == "NOASSERTION" else (spdx or lic.get("key") or "").lower(),
        created=(item.get("created_at") or "")[:10],
        updated=(item.get("pushed_at") or item.get("updated_at") or "")[:10],
        size=f"{int(item.get('size') or 0)} KB", likes=int(item.get("stargazers_count") or 0),
        description=" ".join((item.get("description") or "").split())[:300])


def _popular(entry: dict) -> bool:
    return (int(entry.get("downloads") or 0) >= MIN_DOWNLOADS
            or int(entry.get("likes") or 0) >= MIN_LIKES)


_BENCHY = re.compile(r"bench|eval", re.I)


def _benchmark_repo(item: dict) -> bool:
    return bool(_BENCHY.search(item.get("full_name") or "")
                or "benchmark" in (item.get("topics") or []))


def _get_json(url: str, params: dict | None = None):
    """GET a registry API as JSON; GitHub goes through `gh api` for its token."""
    if url.startswith(GH_SEARCH):
        from harness import github
        path = "search/repositories?" + urllib.parse.urlencode(params or {})
        return json.loads(github._gh(path))
    import httpx
    for attempt in range(5):
        r = httpx.get(url, params=params, timeout=60, follow_redirects=True)
        if r.status_code != 429 and r.status_code < 500:
            break
        time.sleep(float(r.headers.get("retry-after") or 2 ** attempt))
    r.raise_for_status()
    return r.json()


def _due(conn, name: str, now: float, force: bool) -> bool:
    from harness import memory_store as ms
    row = ms.source_row(conn, name)
    if force or not row or not row["last_read_at"]:
        return True
    return now - float(row["last_read_at"]) >= feeds.interval_days() * 86400


def _read_hf(lane: str, get) -> list[Benchmark]:
    found: dict[str, Benchmark] = {}
    for q in LANE_QUERIES[lane]["hf"]:
        for sort in HF_SORTS:
            params = {**q, "sort": sort, "direction": -1, "limit": HF_LIMIT, "full": "true"}
            for entry in get(HF_DATASETS, params) or []:
                if entry.get("id") and _popular(entry):
                    found.setdefault(entry["id"], from_hf(entry, lane))
    return list(found.values())


def _read_gh(lane: str, get) -> list[Benchmark]:
    params = {"q": LANE_QUERIES[lane]["gh"], "sort": "updated", "order": "desc",
              "per_page": GH_LIMIT}
    items = (get(GH_SEARCH, params) or {}).get("items") or []
    return [from_github(i, lane) for i in items if i.get("full_name") and _benchmark_repo(i)]


def sweep(conn, lanes=None, get=None, now: float | None = None,
          force: bool = False) -> list[Benchmark]:
    """Read each lane's registries once per discovery interval and record every source found."""
    from harness import memory_store as ms
    get = get or _get_json
    now = time.time() if now is None else float(now)
    out: list[Benchmark] = []
    # A lane with no queries has no benchmark source to read, which is not a failed read. #601.
    for lane in [x for x in (lanes or sorted(LANE_QUERIES)) if x in LANE_QUERIES]:
        for registry, read in (("huggingface", _read_hf), ("github", _read_gh)):
            name = f"{KIND}:{registry}:{lane}"
            if not _due(conn, name, now, force):
                continue
            try:
                found = read(lane, get)
            except Exception as exc:  # noqa: BLE001
                ms.record_source(conn, name, kind=KIND, ok=False, error=str(exc), at=now)
                continue
            for b in found:
                ms.record_benchmark(conn, b, at=now)
            ms.record_source(conn, name, kind=KIND, url=HF_DATASETS if registry ==
                             "huggingface" else GH_SEARCH, at=now)
            out.extend(found)
    return out


def dataset_info(repo: str, get=None) -> Benchmark | None:
    """One dataset's full card: columns, rows and revision that a search entry lacks."""
    get = get or _get_json
    return None if not repo else from_hf(get(f"{HF_DATASETS}/{repo}"), "")


# ---- training cutoffs and declared datasets (#414, #470) -------------------------

_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}
_CUTOFF = re.compile(
    r"(?:knowledge|training[- ]data|data|training)\s+cut-?off\D{0,20}?"
    r"(?:(?P<month>" + "|".join(_MONTHS) + r")\s+(?P<year>20\d\d)|(?P<iso>20\d\d-\d\d))", re.I)


def card_cutoff(text: str) -> str:
    """A training cutoff stated in a model card's prose, as YYYY-MM; '' if none."""
    for m in _CUTOFF.finditer(text or ""):
        if m.group("iso"):
            return m.group("iso")
        month = _MONTHS.get(m.group("month").lower())
        if month:
            return f"{m.group('year')}-{month:02d}"
    return ""


def _quantized_parent(model: dict) -> str:
    prefix = "base_model:quantized:"
    return next((t[len(prefix):] for t in model.get("tags") or [] if t.startswith(prefix)), "")


def training_facts(model: dict, parent: dict | None = None, readme: str = "") -> dict:
    """Cutoff (card, else release date; a quantization's is its parent's) and declared datasets."""
    card = model.get("cardData") or {}
    datasets = list(card.get("datasets") or []) + list((parent or {}).get("cardData", {})
                                                       .get("datasets") or [])
    stated = card_cutoff(readme)
    if stated:
        return {"cutoff": stated, "cutoff_source": "card", "datasets": datasets}
    dated = parent if parent and _quantized_parent(model) else model
    return {"cutoff": (dated.get("createdAt") or "")[:10],
            "cutoff_source": "release" if dated.get("createdAt") else "",
            "datasets": datasets}


def read_training(repo: str, get=None, readme_get=None) -> dict:
    """Fetch a candidate's card (and a quantization's parent) and return its training facts."""
    get = get or _get_json
    model = get(f"{HF_MODELS}/{repo}")
    parent_repo = _quantized_parent(model)
    parent = get(f"{HF_MODELS}/{parent_repo}") if parent_repo else None
    readme = ""
    if readme_get is not None:
        readme = readme_get(parent_repo or repo)
    return training_facts(model, parent, readme)


def _original(bench: Benchmark, known) -> Benchmark | None:
    """The earliest older benchmark this one's name copies: a mirror is dated by its original."""
    from harness import contamination as ct
    mine = bench.name.split(":", 1)[-1]
    older = [k for k in known or () if k.name != bench.name and k.created
             and bench.created and k.created < bench.created
             and ct.declared(k.name.split(":", 1)[-1], [mine])]
    return min(older, key=lambda k: k.created) if older else None


def contamination(bench: Benchmark, training: list[dict], known=()) -> tuple[str, str]:
    """declared, predates, after-cutoff or unknown, and why; a clean date is not proof of absence."""
    from harness import contamination as ct
    source = bench.name.split(":", 1)[-1]
    training = [t for t in training if t.get("lane", "") in ("", bench.lane)]
    for t in training:
        if bench.registry == "huggingface" and ct.declared(source, t.get("datasets") or []):
            return "declared", f"{t['candidate']} lists it in its training data"
    dated = [t for t in training if t.get("cutoff")]
    if not dated or not bench.created:
        return "unknown", "no creation date" if dated else "no candidate cutoff recorded"
    newest = max(dated, key=lambda t: t["cutoff"])
    original = _original(bench, known)
    if original and original.created[:len(newest["cutoff"])] <= newest["cutoff"]:
        return "predates", (f"looks like a copy of {original.name} (created {original.created}), "
                            f"before {newest['candidate']}'s cutoff {newest['cutoff']}")
    if bench.created[:len(newest["cutoff"])] <= newest["cutoff"]:
        return "predates", (f"created {bench.created}, before {newest['candidate']}'s "
                            f"cutoff {newest['cutoff']}")
    return "after-cutoff", f"created {bench.created}, after every candidate cutoff"
