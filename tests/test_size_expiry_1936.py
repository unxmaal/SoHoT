"""#1936: a cached HF size expires, a few stale entries a process, so a repo's later weights reach its size."""
import json

from harness import inspect as ins


def listing(size, sha):
    return lambda url: json.dumps({"sha": sha, "pipeline_tag": "text-generation", "tags": [],
                                   "siblings": [{"rfilename": "model.safetensors", "size": size}]})


def test_a_stale_entry_follows_the_repos_new_weights():
    cache = {}
    assert ins.hf_size("org/x", fetch=listing(7, "a1"), cache=cache) == 7
    assert ins.hf_size("org/x", fetch=listing(9, "b2"), cache=cache) == 7
    cache["org/x"]["at"] = 1.0
    assert ins.hf_size("org/x", fetch=listing(9, "b2"), cache=cache) == 9
    assert cache["org/x"]["at"] > 1.0


def test_an_entry_from_an_older_release_still_reads_and_is_asked_again():
    old = {"size": 7, "ceiling": ins.ceiling_bytes(), "pipeline_tag": "text-generation", "tags": []}
    got = ins.hf_facts("org/x", fetch=listing(9, "b2"), cache={"org/x": dict(old)})
    assert got["size"] == 9
    # What an older release's reader asks of an entry this one writes. #1617.
    entry = ins.cache_entry({"pipeline_tag": "text-generation"}, 9, ins.ceiling_bytes())
    assert "pipeline_tag" in entry and entry.get("ceiling") == ins.ceiling_bytes() and int(entry["size"]) == 9


def test_one_process_asks_for_at_most_its_share_of_stale_entries_and_keeps_the_rest():
    asked = []
    old = {"size": 7, "ceiling": ins.ceiling_bytes(), "pipeline_tag": "text-generation", "tags": []}
    cache = {f"org/m{i}": dict(old) for i in range(ins.SIZE_REFRESHES + 3)}
    for name in list(cache):
        ins.hf_facts(name, fetch=lambda url: asked.append(url) or listing(9, "b2")(url), cache=cache)
    assert len(asked) == ins.SIZE_REFRESHES
    assert sorted(e["size"] for e in cache.values()) == [7] * 3 + [9] * ins.SIZE_REFRESHES


def test_a_stale_entry_the_registry_will_not_answer_keeps_its_size():
    from harness import feeds

    def limited(url):
        raise feeds.RateLimitedFeed("429")
    old = {"size": 7, "ceiling": ins.ceiling_bytes(), "pipeline_tag": "text-generation", "tags": []}
    assert ins.hf_facts("org/x", fetch=limited, cache={"org/x": old})["size"] == 7


def test_inspect_saves_a_refreshed_size_that_adds_no_entry(tmp_path):
    from tests.test_harness_inspect import tree
    tree(tmp_path / "org__app", {"app.py": 'load("org/m-1b")\nif __name__ == "__main__":\n    main()\n', ".git/HEAD": ""})
    old = {"size": 7, "ceiling": ins.ceiling_bytes(), "pipeline_tag": "text-generation", "tags": []}
    ins._write_size_cache({"org/m-1b": old})
    ins.inspect("org/app", tmp_path, run=lambda *a, **k: "2026-01-01T00:00:00+00:00",
                facts=lambda model_id, cache=None: ins.hf_facts(model_id, fetch=listing(9, "b2"), cache=cache))
    assert ins._size_cache()["org/m-1b"]["size"] == 9
