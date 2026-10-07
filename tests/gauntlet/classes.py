"""This repo's bindings to the gauntlet skill's classes; definitions live only in the skill (#492)."""


def _i(*issues, rules=()):
    return [{"issue": n} for n in issues] + [{"rule": n} for n in rules]


INDEX = {
    "a-fact-about-the-harness-recorded-as-a-verdict-on-the-subject": {
        "detector": "harness_verdicts",
        "waivers": {
            "harness/commands/discover.py:_report_inspect":
                "ins.Gone is a definite registry 404, an answer about the candidate; unreachable stays unanswered",
            "harness/commands/measure.py:cmd_verify":
                "soh verify reports on the harness's own lane default and writes nothing to the store",
        },
        "instances": _i(211, 223, 230, 293, 305, 366, 378, 380, 381, 385, 399, 401, 404, 406,
                        rules=(270, 282, 298, 331, 378, 385, 393)),
        "scanners": []},
    "one-question-two-answers": {
        "detector": "duplicated_literals",
        "instances": _i(38, 51, 115, 117, 140, 153, 155, 157, 187, 207, 224, 249, 345, 520, rules=(268,)),
        "scanners": ["tests/test_duplicated_policy.py::test_every_duplicated_policy_still_has_a_guard"]},
    "a-platform-primitive-assumed-universal": {
        "instances": _i(123, 126, 127, 129, 144, 150, 174, 255, 442, rules=(192,)),
        "scanners": [
            "tests/test_portability.py::test_no_text_file_is_read_or_written_without_an_explicit_encoding",
            "tests/test_portability.py::test_no_script_uses_a_bsd_only_df_flag",
            "tests/test_script_modes.py::test_a_script_with_a_shebang_is_executable_in_the_index",
            "tests/test_no_drop_column.py::test_no_test_drops_a_column"]},
    "each-half-verified-against-its-own-spec-the-seam-against-nothing": {
        "detector": "env_seams",
        "waivers": {
            "env:NEEDLE_BIN":
                "a person's override of the fetched needle binary; nothing in this repo sets it (#534)",
            "env:NEEDLE_MODEL":
                "a person's override of the fetched needle weights; nothing in this repo sets it (#534)",
        },
        "instances": _i(72, 77, 81, 167, 183, 214, 219, 240, 297, 335, 343, 378, 384, 389, 420, 424, 521,
                        542, rules=(247, 379, 474)),
        "scanners": []},
    "a-metric-quoted-without-a-negative-control": {
        "review": r"\b(?:auc|brier|ece|accuracy|precision|recall|win_rate|p_value|significan\w*|kendall\w*|spearman\w*)\b",
        "instances": _i(5, 85, 86, 175, 308, rules=(211, 217, 349)),
        "scanners": []},
    "a-number-without-its-configuration": {
        "instances": _i(88, 141, rules=(238,)),
        "scanners": ["tests/test_gauntlet_scanners.py::test_numbers_without_their_configuration_are_an_inventory_that_only_shrinks",
                     "tests/test_harness_assertions.py::test_no_unqualified_cost_ships"]},
    "a-part-s-cost-reported-as-the-whole-s": {
        "instances": _i(89),
        "scanners": ["tests/test_harness_assertions.py::test_no_unqualified_cost_ships"]},
    "a-check-whose-input-differs-between-the-desk-and-ci": {
        "instances": _i(109, 458, 537, rules=(231, 273)),
        "scanners": ["tests/test_harness_repo.py::test_the_scanners_use_it",
                     "tests/test_harness_proc_instrument.py::test_one_run_paged_out_under_load_does_not_fail_the_control"]},
    "a-format-assumed-to-generalise": {
        "review": r"[\"'][,;|:][\"']\.join\(|\.split\([\"'][,;|][\"']\)|--\w[\w-]*=\{|\bbatch(?:ed|_size)?\b",
        "instances": _i(390),
        "scanners": []},
    "a-confounded-experiment-the-label-is-not-the-run": {
        "review": r"\b(?:arm|variant|challenger|incumbent)s?\b|\[\"(?:label|run_id)\"\]",
        "instances": _i(222, 238, 282, 333, rules=(215, 225)),
        "scanners": []},
    "external-state-with-no-assertion-on-it": {
        "instances": _i(147, 339, rules=(239,)),
        "scanners": ["tests/test_harness_obtainable.py::test_the_mlx_config_is_clean"]},
    "a-statistic-blind-to-the-effect-under-test": {
        "review": r"\b(?:mean|median|average|stdev|pass_rate|percentile)\b|statistics\.",
        "instances": _i(87),
        "scanners": []},
    "identity-by-name-not-by-content": {
        "review": r"\b(?:cache_key|dedup\w*|digest|etag|lru_cache)\b|\bseen\s*(?:=|\.add\()",
        "instances": _i(110, 116, 124, 277, 337, rules=(297,)),
        "scanners": []},
    "a-reference-that-no-longer-resolves": {
        "instances": _i(145),
        "scanners": ["tests/test_prose_references.py::test_every_path_named_in_prose_reaches_the_reader"]},
    "silent-truncation-or-a-partial-read-assumed-complete": {
        "review": r"\.read\(\d+\)|\bhead\s+-[nc]|\btail\s+-[nc]|max_(?:chars|bytes)|truncat\w*|\[:\d{3,}\]",
        "instances": _i(241),
        "scanners": []},
    "a-consumer-limits-before-it-filters-for-what-it-can-act-on": {
        "review": r"\[:\s*(?:n|limit|top|k|a\.top|a\.limit)\s*\]|\bLIMIT \?",
        "instances": _i(194, 209, 292, 376, 386, rules=(330, 377)),
        "scanners": []},
    "one-column-two-meanings": {
        "review": r"(?i)\bADD COLUMN\b|\bCREATE TABLE\b",
        "instances": _i(227, 461, 463, 471, rules=(277,)),
        "scanners": []},
    "a-shared-fixed-resource-in-tests": {
        "instances": _i(426, 505, rules=(384, 441)),
        "scanners": ["tests/test_gauntlet_scanners.py::test_no_test_binds_or_writes_a_fixed_shared_resource"]},
    "a-fake-that-does-not-model-the-real-process-s-environment": {
        "review": r"\bfake\w*\.(?:write_text|chmod)\(|#!/usr/bin/env|\bPopen\(",
        "review_paths": r"^tests/",
        "instances": _i(399),
        "tier": 2,
        "tier_reason": "whether a fake matches the real process depends on how the code under test launches it; "
                       "a scan sees only a proxy (a shebang, a skip marker)",
        "scanners": []},
    "a-transport-change-that-silently-changes-the-payload": {
        "review": r"\bstream=|urlopen\(|requests\.(?:get|post)\(|httpx\.|\bgzip\b|\bproxy\b",
        "instances": _i(489, rules=(426,)),
        "scanners": []},
    "the-empty-collection": {
        "review": r"/\s*len\(|statistics\.(?:mean|median|stdev)\(|\b(?:max|min)\(\w+\)",
        "instances": _i(118), "scanners": []},
    "an-error-swallowed": {
        "instances": _i(477, 501),
        "scanners": ["tests/test_gauntlet_scanners.py::test_swallowed_errors_are_an_inventory_that_only_shrinks"]},
    "success-assumed-exit-status-unchecked": {
        "instances": _i(328),
        "scanners": ["tests/test_gauntlet_scanners.py::test_no_shell_script_ignores_a_failure_it_could_see"]},
    "partial-failure-leaves-inconsistent-state": {
        "review": r"executemany\(|\.rename\(|os\.replace\(|shutil\.move\(",
        "instances": _i(181), "scanners": []},
    "order-assumed-on-unordered-data": {
        "review": r"\bfor \w+ in (?:set\(|\w+\.keys\(\)|\w+\.glob\(|\w+\.iterdir\(|os\.listdir\()",
        "instances": _i(252), "scanners": []},
    "external-input-trusted": {
        "review": r"shell=True|\beval\(|\bexec\(|os\.system\(|f\"(?:SELECT|INSERT|UPDATE|DELETE)\b",
        "instances": _i(246, 363, 368, rules=(374,)), "scanners": []},
    "toctou-check-then-act": {
        "review": r"if (?:not )?\w[\w.]*\.(?:exists|is_file|is_dir)\(\)|os\.path\.exists\(|\[ -[ef] ",
        "instances": _i(422), "scanners": []},
    "non-idempotent-retry": {
        "review": r"(?i)\bretr(?:y|ies)\b|\bbackoff\b|\brerun\b|\bresum(?:e|able)\b",
        "instances": _i(184, 496, rules=(432,)), "scanners": []},
    "resource-leak-on-the-error-path": {
        "review": r"=\s*open\(|\bPopen\(|socket\.socket\(|mkdtemp\(|\.acquire\(",
        "instances": _i(444), "scanners": []},
    "mutable-shared-or-default-state": {
        "instances": _i(303, 495, rules=(334, 431)),
        "scanners": ["tests/test_gauntlet_scanners.py::test_no_function_has_a_mutable_default"]},
    "empty-versus-absent-conflated": {
        "review": r"\bor\s+(?:[\"']{2}|0|\[\]|\{\})(?![\w.])|==\s*[\"']{2}",
        "instances": _i(195), "scanners": []},
    "regex-over-or-under-matching": {
        "review": r"\bre\.(?:compile|search|match|fullmatch|findall|sub|split)\(",
        "instances": _i(49), "scanners": []},
    "flaky-by-time-or-randomness": {
        "review": r"time\.time\(|datetime\.now\(|\brandom\.\w+\(|\bsleep\(\d",
        "instances": _i(349), "scanners": []},
    "assuming-a-single-result": {
        "review": r"\bhead -1\b|\.first\(\)|\bnext\(iter\(|\.group\(1\)",
        "instances": _i(438), "scanners": []},
    "cwd-or-script-location-path-assumption": {
        "review": r"os\.getcwd\(|Path\.cwd\(|Path\([\"']\.{1,2}/|\bsource\s+\./|open\([\"']\./",
        "instances": _i(108, 151), "scanners": []},
    "cleanup-missing-on-failure": {
        "review": r"mkdtemp\(|\btrap\b|launchctl\s+(?:load|bootstrap)|\.start\(\)",
        "instances": _i(373), "scanners": []},
    "a-guard-built-and-tested-that-nothing-invokes": {
        "detector": "unreached_guards",
        "instances": _i(1, 137, 143, 172, 182, 191, 279, 284, rules=(251,)), "scanners": []},
    "a-test-double-that-never-reaches-the-code-under-test": {
        "instances": _i(517, 518, 519, 529, 530, 536, rules=(445,)),
        "scanners": ["tests/test_module_layout.py::test_every_patch_reaches_the_code_that_reads_it",
                     "tests/test_no_real_runtime.py::test_a_runtime_binary_answers_as_absent_and_is_recorded"]},
    "an-input-accepted-and-silently-ignored": {
        "detector": "ignored_options",
        "instances": _i(60, 103, 215, 315, 329, rules=(355,)),
        "scanners": ["tests/test_json_everywhere.py::test_no_verb_ignores_json"]},
    "a-fact-recorded-without-its-context": {
        "review": r"(?i)\bINSERT INTO\b|json\.dump\(",
        "instances": _i(266, 270, 281, 331, 341, 450, rules=(293, 356)), "scanners": []},
    "a-non-production-run-writes-live-state": {
        "instances": _i(29, 188, 290, 455, 512, 513, rules=(414,)),
        "scanners": ["tests/test_gauntlet_scanners.py::test_the_live_home_is_derived_only_in_harness_paths"]},
    "a-closed-table-fronting-an-open-set": {
        "detector": "closed_tables",
        "instances": _i(213, 228, 245, 263, 298, 318, 379, 380, 387, rules=(379, 419)), "scanners": []},
    "state-is-whichever-row-came-last": {
        "detector": "latest_row_state",
        "waivers": {
            "harness/adopt.py:fit":
                "ORDER BY peak_kb DESC is the largest measured peak, not the newest row (#533)",
            "harness/commands/judge.py:_say_adopted":
                "prints the adoption this command just wrote; display only (#533)",
            "harness/memory_store/transitions.py:decide":
                "dedupes an exact repeat for a candidate no proposal names; state lives in proposals.state (#409)",
            "harness/memory_store/migrations/columns.py:drop_dead_columns":
                "a one-time migration lifting the newest recorded value before the column is dropped",
            "harness/memory_store/migrations/prose.py:size_sources":
                "a one-time migration reading the newest inspect size, which is a measurement, not a state",
            "harness/reverify.py:judge":
                "the run a queued job stored; a retried job's newest run is its latest attempt (#526)",
        },
        "instances": _i(225, 253, 254, 393, 399, rules=(382, 389)), "scanners": []},
    "a-proxy-checked-in-place-of-the-property": {
        "review": r"\.exists\(\)|\.is_dir\(\)|returncode == 0|status_code == 200|\.st_size\b",
        "instances": _i(68, 101, 173, 196, 283, 322, 365), "scanners": []},
    "a-rule-change-leaves-old-decisions-standing": {
        "review": r"\bTRANSITIONS\b|\bREOPENS\b|\bthreshold\w*\s*=|\bpolicy\s*=",
        "instances": _i(73, 230, 295, 301, rules=(333,)), "scanners": []},
    "one-default-tuned-for-one-member-applied-to-all": {
        "detector": "member_defaults",
        "waivers": {
            "harness/contamination.py:gateway_ask(max_tokens)":
                "a contamination probe's reply budget, the same question to every model by design (#531)",
        },
        "instances": _i(355, 401, 498), "scanners": []},
    "history-reconstructed-from-present-state": {
        "review": r"(?i)\bbackfill\w*|\bUPDATE\s+\w+\s+SET\b",
        "instances": _i(506, 516, rules=(292,)), "scanners": []},
}

# Proposed classes with no skill entry yet; add the entry to SKILL.md, regenerate the snapshot, move here into INDEX.
PENDING = {}

UNCLASSIFIED = {
    6: "upstream model behaviour (Chatterbox runs past its input), no failing in this repo's logic",
    27: "upstream break inside mflux against the installed mlx, not ours to fix",
    136: "privacy disclosure in prose; handled by the privacy scanner, no logical class",
    371: "a lock held wider than the resource it guards; one instance, no class yet",
    374: "a policy (reference models are never defaults) that was never written down; one instance",
    396: "producer outruns consumer with no backpressure; one instance, no class yet",
}
