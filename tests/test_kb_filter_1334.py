"""#1334: the KB hit filter, its fallbacks and its eval, on synthesized searches and transcripts."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from harness import cli
from harness import kb_filter as kf

T0 = datetime(2026, 10, 20, tzinfo=timezone.utc)
SEARCH = "mcp__mcm-engine__search"
K = kf.Knobs(min_hits=4, floor=2, hit_chars=600, need_chars=2000, chunk=12, reply=200)
FOOTER = "\n\n(summary view — fetch any full body with get_entry(\"<type>\", <id>).)"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def body(*ids, pad=40):
    return "\n\n".join(f"[{kind} #{n}] title {n}: " + "w" * pad + "\n  Tags: t" for kind, n in ids) + FOOTER


def item(key, n, gold, at=0.0, need="fix the widget", pad=400):
    hits = [{"kind": "RULE", "id": str(100 + p), "text": f"[RULE #{100 + p}] t " + "w" * pad} for p in range(1, n + 1)]
    return {"key": key, "at": at, "query": "widget", "need": need, "header": "", "hits": hits, "footer": "",
            "tokens": sum(kf.tokens(h["text"]) for h in hits), "gold": gold}


def test_a_result_parses_into_header_hits_and_footer_and_renders_back_whole():
    text = body(("KNOWLEDGE/FINDING", 1), ("RULE", 2), ("ERROR", 3))
    text = text.replace("[RULE #2] title 2:", "[RULE #2] title 2:\n\n## shape\n\n    code")
    header, hits, footer = kf.parse(text)
    assert [(h["kind"], h["id"]) for h in hits] == [("KNOWLEDGE/FINDING", "1"), ("RULE", "2"), ("ERROR", "3")]
    assert "## shape" in hits[1]["text"] and footer == FOOTER and header == ""
    assert kf.render(header, hits, [1, 2, 3], footer) == text
    assert kf.unwrap(json.dumps({"result": text})) == (text, True)


def test_a_filtered_result_keeps_order_and_names_every_dropped_id():
    header, hits, footer = kf.parse(body(*[("RULE", n) for n in range(1, 6)]))
    out = kf.render(header, hits, [4, 2], footer)
    assert out.index("[RULE #2] title") < out.index("[RULE #4] title")
    assert "[RULE #1] title" not in out
    assert "also matched: [RULE #1], [RULE #3], [RULE #5]" in out and out.endswith(FOOTER)


@pytest.mark.parametrize("chosen", [None, [], [0], [99], ["x"], 7])
def test_any_doubt_about_the_choice_shows_every_hit(chosen):
    it = item("k", 6, [1])
    assert kf.guard(it["hits"], chosen, it["query"], it["need"], K) == [1, 2, 3, 4, 5, 6]


def test_a_small_search_is_never_filtered():
    it = item("k", K.min_hits - 1, [1])
    assert kf.guard(it["hits"], [1], "", "", K) == list(range(1, K.min_hits))


def test_a_hit_the_caller_asked_for_by_id_is_always_kept_and_the_floor_holds():
    it = item("k", 8, [1])
    assert kf.guard(it["hits"], [3], "RULE #106", "see #108", K) == [3, 6, 8]
    assert kf.guard(it["hits"], [5], "", "", K, order=[2, 5, 1]) == [2, 5]


def test_decide_asks_in_chunks_and_a_failed_call_falls_back_to_every_hit(tmp_path):
    it = item("k", K.chunk + 2, [3])
    asked = []

    def ask(question, schema, context=""):
        asked.append(sorted(schema, key=lambda f: int(f.split("_")[1])))
        return {"answers": {f: "true" for f in schema},
                "probabilities": {f: {"true": 0.9 if f == "result_3" else 0.1, "false": 0.1} for f in schema}}

    probs = kf.decide_scores(it, ask, K)
    assert len(asked) == 2 and asked[1] == [f"result_{K.chunk + 1}", f"result_{K.chunk + 2}"]
    assert probs[2] == 0.9 and probs[0] == 0.1
    assert kf.decide_keep(it, probs, 0.5, K) == [1, 3]

    def broken(*a, **k):
        raise RuntimeError("lane down")

    got = kf.score([it], "decide", tmp_path / "s.jsonl", broken, K)
    assert got == {"k": None} and kf.scored(tmp_path / "s.jsonl") == {"k": None}
    assert kf.decide_keep(it, got["k"], 0.5, K) == list(range(1, K.chunk + 3))


def test_extract_reads_a_list_and_no_list_means_every_hit():
    it = item("k", 6, [2])
    assert kf.extract_choice(it, lambda *a, **k: {"text": "Results: [2, 5]"}, K) == [2, 5]
    assert kf.extract_choice(it, lambda *a, **k: {"text": "none of them"}, K) is None
    assert kf.guard(it["hits"], None, "", "", K) == [1, 2, 3, 4, 5, 6]


def test_the_position_arm_reaches_the_same_kept_tokens():
    it = item("k", 10, [9])
    one = kf.tokens(it["hits"][0]["text"])
    assert kf.by_position(it, 3 * one) == [1, 2, 3]
    assert kf.by_position(it, 3 * one + 1) == [1, 2, 3, 4]
    assert kf.by_type({**it, "hits": [{**h, "kind": k} for h, k in zip(it["hits"], "AABBBAC")]}) == [1, 2, 3, 4, 7]


def test_a_plant_sits_at_position_six_or_later_and_is_its_only_gold():
    planted = kf.plant([item(f"k{n}", 8, [1], need=f"need number {n}") for n in range(30)], n=20)
    assert len(planted) == 20
    for p in planted:
        (at,) = p["gold"]
        assert at >= 6 and p["hits"][at - 1]["id"] == "990001" and p["need"] in p["hits"][at - 1]["text"]


def _scores(items, good):
    return {it["key"]: [0.9 if p in it["gold"] or not good else 0.05 for p in range(1, len(it["hits"]) + 1)]
            for it in items}


def test_the_gate_passes_a_filter_that_keeps_late_referenced_hits_and_fails_one_that_keeps_all():
    tune = [item(f"t{n}", 12, [8, 11], at=n) for n in range(10)]
    held = [item(f"h{n}", 12, [7, 12], at=100 + n) for n in range(40)]
    planted = kf.plant(held)
    good = kf.report(tune, held, _scores(tune + held + planted, True), {}, K, planted)
    assert good["arms"]["decide"]["recall"] == 1.0 and good["gate"] == []
    assert good["vs_position"]["won"] > 0 and good["vs_position"]["lost"] == 0
    assert good["arms"]["decide"]["kept_share"] < 0.25
    flat = kf.report(tune, held, _scores(tune + held, False), {}, K, None)
    assert flat["arms"]["decide"]["kept_share"] > 0.99
    assert any("position" in w for w in flat["gate"]) and "planted check not run" in flat["gate"]


def test_the_threshold_comes_from_the_tuning_searches_only():
    tune = [item(f"t{n}", 8, [2], at=n) for n in range(5)]
    scores = {it["key"]: [0.1, 0.4, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1] for it in tune}
    assert kf.threshold(tune, scores, K) == 0.4


def call(mid, uses=(), text=None, at=T0):
    content = [{"type": "tool_use", "id": uid, "name": name, "input": inp} for uid, name, inp in uses]
    if text:
        content.insert(0, {"type": "text", "text": text})
    return {"type": "assistant", "timestamp": iso(at), "message": {
        "id": mid, "role": "assistant", "content": content, "usage": {"input_tokens": 10, "output_tokens": 1}}}


def result(uid, text, at=T0):
    return {"type": "user", "timestamp": iso(at), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid, "content": text}]}}


def session(root, lines, name="s1"):
    p = root / "p" / f"{name}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/kb_filter.py:_TYPE")
def test_a_kind_named_beside_an_id_maps_to_its_entry_type_and_any_other_kind_stands_for_itself():
    said = call("m1", text="per DECISION #5, Insight #6, KB FINDING #7, negative #8 and RULE #9; issue #10")
    assert kf.named([said]) == {("knowledge", "5"): 0, ("knowledge", "6"): 0, ("knowledge", "7"): 0,
                                ("negative", "8"): 0, ("rule", "9"): 0}


def test_the_labelled_set_takes_the_need_query_hits_and_later_references(tmp_path):
    shown = json.dumps({"result": body(*[("RULE", n) for n in range(11, 19)], pad=600)})
    session(tmp_path, [
        {"type": "user", "timestamp": iso(T0), "message": {"role": "user", "content": "the opening prompt"}},
        call("m0", text="an older thought"), call("m1", text="I need the widget fix"),
        call("m2", [("s1", SEARCH, {"query": "widget"})]), result("s1", shown),
        call("m3", text="RULE #17 says so, and issue #13 is open; ERROR #14 too"),
        call("m4", [("g1", "mcp__mcm-engine__get_entry", {"entity_type": "rule", "entry_id": 12})]),
        result("g1", "body"),
        call("m5", [("s2", SEARCH, {"query": "unused"})]), result("s2", shown)])
    (got,) = kf.labelled(tmp_path, since=0)
    assert (got["query"], got["need"], got["gold"], len(got["hits"])) == (
        "widget", "I need the widget fix", [2, 3, 4, 7], 8)
    assert got["footer"] == FOOTER
    (strict,) = kf.labelled(tmp_path, since=0, strict=True)
    assert strict["gold"] == [2, 7]


def test_soh_kb_filter_eval_reports_every_arm_from_stored_scores(tmp_path, capsys):
    shown = json.dumps({"result": body(*[("RULE", n) for n in range(11, 19)], pad=600)})
    lines = []
    for d in range(14):
        at = T0 + timedelta(days=d)
        lines += [call(f"a{d}", text="widget work", at=at), call(f"b{d}", [(f"s{d}", SEARCH, {"query": "w"})], at=at),
                  result(f"s{d}", shown, at=at), call(f"c{d}", text="RULE #17 applies", at=at)]
    session(tmp_path / "t", lines)
    work = tmp_path / "w"
    args = ["kb-filter", "--eval", "--dir", str(work), "--root", str(tmp_path / "t"), "--since", "2026-10-01"]
    assert cli.main(args + ["--no-model", "--json"]) == 1
    capsys.readouterr()
    items = kf.load(work / "set.jsonl")
    (work / "decide.jsonl").write_text("".join(
        json.dumps({"key": it["key"], "answer": [0.9 if p == 7 else 0.1 for p in range(1, 9)]}) + "\n"
        for it in items), encoding="utf-8")
    assert cli.main(args + ["--no-model", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data["arms"]) == {"decide", "lexical", "combo", "position", "type"}
    assert data["arms"]["decide"]["recall"] == 1.0 and data["held_out"] == 8
    assert json.loads((work / "report.json").read_text(encoding="utf-8"))["threshold"] == data["threshold"]
    assert data["knobs"] == K._asdict() and data["ship"]["arm"] in ("lexical", "decide", "combo", "none")
    assert json.loads((work / "vocab.json").read_text(encoding="utf-8"))["n"] == 6 * 8


def test_the_threshold_is_the_highest_cut_reaching_the_target_as_a_scan_finds_it():
    import random
    rng = random.Random(7)
    items = [item(f"t{n}", 10, rng.sample(range(1, 11), 2)) for n in range(30)]
    scores = {it["key"]: [rng.random() for _ in range(10)] for it in items}
    for target in (0.5, 0.8, 0.96, 1.0):
        scan = next((c for c in sorted({s for v in scores.values() for s in v}, reverse=True)
                     if kf.recall(items, {it["key"]: kf.decide_keep(it, scores[it["key"]], c, K)
                                          for it in items})[0] >= target), 0.0)
        assert kf.threshold(items, scores, K, target) == scan


def lex_item(need, hits, query="widget"):
    hits = [{"kind": "RULE", "id": str(200 + p), "text": f"[RULE #{200 + p}] {t}"} for p, t in enumerate(hits, 1)]
    return {"key": need, "query": query, "need": need, "header": "", "hits": hits, "footer": "",
            "tokens": sum(kf.tokens(h["text"]) for h in hits), "gold": []}


FILLER = [f"unrelated topic number {n} about gardening and soup" for n in range(9)]


def test_the_lexical_arm_scores_rare_shared_words_over_common_ones_with_no_model():
    vocab = kf.vocabulary([lex_item("x", FILLER + ["the widget gearbox jams", "widget"])])
    it = lex_item("the gearbox jams on the widget", FILLER + ["gearbox jams in cold", "the widget"])
    got = kf.lexical_scores(it, vocab, K)
    assert got[9] == 1.0 and got[10] < got[9] and max(got[:9]) < got[10]
    assert kf.lexical_scores(lex_item("", ["a", "b"], query=""), vocab, K) == [0.0, 0.0]


def test_mean_and_budget_arms_line_up_per_hit_and_stop_at_the_budget():
    assert kf.mean_scores({"a": [1.0, 0.0], "b": [1.0], "c": None}, {"a": [0.0, 1.0], "b": [1.0, 0.0]}) == \
        {"a": [0.5, 0.5]}
    it = item("k", 6, [5])
    one = kf.tokens(it["hits"][0]["text"])
    assert kf.budget_keep(it, [0.1, 0.2, 0.3, 0.4, 0.9, 0.5], 2 * one, K) == [5, 6]
    assert kf.budget_keep(it, None, one, K) == [1, 2, 3, 4, 5, 6]


def _out(gates=None, vs=None, kept=None):
    gates = gates or {}
    vs = vs or {}
    kept = kept or {}
    return {"arms": {a: {"tokens_kept": kept.get(a, 100)} for a in ("decide", "lexical", "combo")},
            "gates": {a: gates.get(a, []) for a in ("decide", "lexical", "combo")},
            "vs_lexical": {a: vs.get(a, {"won": 1, "lost": 1, "p": 1.0}) for a in kf.LOCAL},
            "thresholds": {"decide": 0.3, "lexical": 0.1, "combo": 0.2}}


def test_a_local_arm_ships_only_when_it_beats_lexical_at_equal_tokens_and_keeps_no_more():
    win = {"won": 30, "lost": 5, "p": 0.001}
    assert kf.ship(_out())["arm"] == "lexical"
    assert kf.ship(_out(vs={"combo": {"won": 13, "lost": 7, "p": 0.2632}}))["arm"] == "lexical"
    assert kf.ship(_out(vs={"combo": win}))["arm"] == "combo"
    assert kf.ship(_out(vs={"combo": win}, kept={"combo": 101}))["arm"] == "lexical"
    assert kf.ship(_out(vs={"combo": win}, gates={"combo": ["recall"]}))["arm"] == "lexical"
    assert kf.ship(_out(vs={"combo": win, "decide": win}, kept={"decide": 90, "combo": 95})) == \
        {"arm": "decide", "cut": 0.3, "why": []}
    none = kf.ship(_out(gates={"lexical": ["recall 0.9 < 0.95"]}))
    assert none["arm"] == "none" and "lexical: recall 0.9 < 0.95" in none["why"]


NEED = "the gearbox jams on the widget after the firmware update"


def _chosen(arm="lexical", cut=0.5):
    return {"ship": {"arm": arm}, "thresholds": {"decide": 0.5, "lexical": cut, "combo": 0.5},
            "knobs": K._asdict()}


def _event(tmp_path, text, response=None, tool=SEARCH):
    tr = tmp_path / "t.jsonl"
    tr.write_text(json.dumps(call("m1", text=NEED)) + "\n" + json.dumps(call("m2", [("s1", SEARCH, {})])) + "\n",
                  encoding="utf-8")
    shown = json.dumps({"result": text})
    return {"tool_name": tool, "tool_input": {"query": "widget"}, "transcript_path": str(tr),
            "tool_response": response if response is not None else [{"type": "text", "text": shown}]}


def _search(n=10, at=8):
    rows = [(f"[RULE #{300 + p}] unrelated topic {p} about gardening and soup" if p != at else
             f"[RULE #{300 + p}] {NEED} (planted)") for p in range(1, n + 1)]
    return "\n\n".join(rows) + FOOTER


def test_the_hook_keeps_a_planted_hit_at_position_eight_and_names_the_dropped_ids(tmp_path):
    vocab = kf.vocabulary([lex_item("x", FILLER + [NEED])])
    got = kf.hook(_event(tmp_path, _search()), _chosen(), vocab)
    out = got["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse" and out["updatedMCPToolOutput"] == out["updatedToolOutput"]
    (block,) = out["updatedMCPToolOutput"]
    text = json.loads(block["text"])["result"]
    assert f"[RULE #308] {NEED}" in text and "[RULE #302] unrelated" not in text
    assert "also matched: [RULE #302]" in text and "[RULE #310]" in text and text.endswith(FOOTER)


@pytest.mark.parametrize("shape", ["str", "result", "content"])
def test_the_hook_returns_the_shape_it_was_given(tmp_path, shape):
    vocab = kf.vocabulary([lex_item("x", FILLER + [NEED])])
    text = _search()
    resp = {"str": text, "result": {"result": text}, "content": {"content": [{"type": "text", "text": text}]}}[shape]
    out = kf.hook(_event(tmp_path, text, resp), _chosen(), vocab)["hookSpecificOutput"]["updatedMCPToolOutput"]
    got = {"str": lambda o: o, "result": lambda o: o["result"], "content": lambda o: o["content"][0]["text"]}[shape](out)
    assert "(planted)" in got and "unrelated topic 2 " not in got


def test_the_hook_leaves_the_result_whole_when_it_cannot_judge(tmp_path):
    vocab = kf.vocabulary([lex_item("x", FILLER + [NEED])])
    assert kf.hook(_event(tmp_path, _search(), tool="Read"), _chosen(), vocab) is None
    assert kf.hook(_event(tmp_path, _search()), _chosen("none"), vocab) is None
    assert kf.hook(_event(tmp_path, _search(n=3, at=2)), _chosen(), vocab) is None
    assert kf.hook(_event(tmp_path, _search(), response={"weird": 1}), _chosen(), vocab) is None
    assert kf.hook(_event(tmp_path, _search()), _chosen(cut=0.0), vocab) is None


def test_a_local_arm_whose_lane_fails_falls_back_to_the_lexical_cut(tmp_path):
    vocab = kf.vocabulary([lex_item("x", FILLER + [NEED])])

    def down(*a, **k):
        raise RuntimeError("lane down")

    def picks_first(question, schema, context=""):
        return {"answers": {}, "probabilities": {f: {"true": 1.0 if f == "result_1" else 0.0} for f in schema}}

    fell = kf.hook(_event(tmp_path, _search()), _chosen("decide"), vocab, down)
    assert "(planted)" in fell["hookSpecificOutput"]["updatedMCPToolOutput"][0]["text"]
    local = kf.hook(_event(tmp_path, _search()), _chosen("decide"), vocab, picks_first)
    text = json.loads(local["hookSpecificOutput"]["updatedMCPToolOutput"][0]["text"])["result"]
    assert "[RULE #301] unrelated" in text and "[RULE #303] unrelated" not in text


def test_soh_kb_filter_hook_prints_the_replacement_or_nothing(tmp_path, capsys):
    import io
    vocab = kf.vocabulary([lex_item("x", FILLER + [NEED])])
    (tmp_path / "report.json").write_text(json.dumps(_chosen()), encoding="utf-8")
    (tmp_path / "vocab.json").write_text(json.dumps(vocab), encoding="utf-8")
    args = cli.build_parser().parse_args(["kb-filter", "--hook", "--dir", str(tmp_path)])
    from harness.commands import kb_filter as cmd
    assert cmd.cmd_kb_filter(args, stdin=io.StringIO(json.dumps(_event(tmp_path, _search())))) == 0
    printed = json.loads(capsys.readouterr().out)
    assert "(planted)" in printed["hookSpecificOutput"]["updatedMCPToolOutput"][0]["text"]
    assert cmd.cmd_kb_filter(args, stdin=io.StringIO("not json")) == 0
    assert capsys.readouterr().out == ""
    (tmp_path / "vocab.json").unlink()
    assert cmd.cmd_kb_filter(args, stdin=io.StringIO(json.dumps(_event(tmp_path, _search())))) == 0
    assert capsys.readouterr().out == ""


def test_soh_kb_filter_settings_prints_a_post_tool_use_block_for_the_search_tool(tmp_path, capsys):
    assert cli.main(["kb-filter", "--settings", "--dir", str(tmp_path), "--json"]) == 0
    block = json.loads(capsys.readouterr().out)["settings"]
    (entry,) = block["hooks"]["PostToolUse"]
    assert entry["matcher"] == SEARCH and entry["hooks"][0]["command"].endswith(
        f"soh kb-filter --hook --dir {tmp_path.resolve()}")
