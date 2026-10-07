"""This repo's bindings to the gauntlet skill's classes; definitions live only in the skill (#492)."""


def _i(*issues, rules=()):
    return [{"issue": n} for n in issues] + [{"rule": n} for n in rules]


INDEX = {
    "a-fact-about-the-harness-recorded-as-a-verdict-on-the-subject": {
        "instances": _i(211, 223, 230, 293, 305, 366, 378, 380, 381, 385, 399, 401, 404, 406,
                        rules=(270, 282, 298, 331, 378, 385, 393)),
        "scanners": []},
    "one-question-two-answers": {
        "instances": _i(38, 51, 115, 117, 140, 153, 155, 157, 187, 207, 224, 249, 345, rules=(268,)),
        "scanners": ["tests/test_duplicated_policy.py::test_every_duplicated_policy_still_has_a_guard"]},
    "a-platform-primitive-assumed-universal": {
        "instances": _i(123, 126, 127, 129, 144, 150, 174, 255, 442, rules=(192,)),
        "scanners": [
            "tests/test_portability.py::test_no_text_file_is_read_or_written_without_an_explicit_encoding",
            "tests/test_portability.py::test_no_script_uses_a_bsd_only_df_flag",
            "tests/test_script_modes.py::test_a_script_with_a_shebang_is_executable_in_the_index",
            "tests/test_no_drop_column.py::test_no_test_drops_a_column"]},
    "each-half-verified-against-its-own-spec-the-seam-against-nothing": {
        "instances": _i(72, 77, 81, 167, 183, 214, 219, 240, 297, 335, 343, 378, 384, 389, 420, 424,
                        rules=(247, 379)),
        "scanners": []},
    "a-metric-quoted-without-a-negative-control": {
        "instances": _i(5, 85, 86, 175, 308, rules=(211, 217, 349)),
        "scanners": []},
    "a-number-without-its-configuration": {
        "instances": _i(88, 141, rules=(238,)),
        "scanners": []},
    "a-part-s-cost-reported-as-the-whole-s": {
        "instances": _i(89),
        "scanners": ["tests/test_harness_assertions.py::test_no_unqualified_cost_ships"]},
    "a-check-whose-input-differs-between-the-desk-and-ci": {
        "instances": _i(109, 458, rules=(231, 273)),
        "scanners": ["tests/test_harness_repo.py::test_the_scanners_use_it"]},
    "a-format-assumed-to-generalise": {
        "instances": _i(390),
        "scanners": []},
    "a-confounded-experiment-the-label-is-not-the-run": {
        "instances": _i(222, 238, 282, 333, rules=(215, 225)),
        "scanners": []},
    "external-state-with-no-assertion-on-it": {
        "instances": _i(147, 339, rules=(239,)),
        "scanners": ["tests/test_harness_obtainable.py::test_the_mlx_config_is_clean"]},
    "a-statistic-blind-to-the-effect-under-test": {
        "instances": _i(87),
        "scanners": []},
    "identity-by-name-not-by-content": {
        "instances": _i(110, 116, 124, 277, 337, rules=(297,)),
        "scanners": []},
    "a-reference-that-no-longer-resolves": {
        "instances": _i(145),
        "scanners": ["tests/test_prose_references.py::test_every_path_named_in_prose_reaches_the_reader"]},
    "silent-truncation-or-a-partial-read-assumed-complete": {
        "instances": _i(241),
        "scanners": []},
    "a-consumer-limits-before-it-filters-for-what-it-can-act-on": {
        "instances": _i(194, 209, 292, 376, 386, rules=(330, 377)),
        "scanners": []},
    "one-column-two-meanings": {
        "instances": _i(227, 461, 463, 471, rules=(277,)),
        "scanners": []},
    "a-shared-fixed-resource-in-tests": {
        "instances": _i(426, 505, rules=(384, 441)),
        "scanners": []},
    "a-fake-that-does-not-model-the-real-process-s-environment": {
        "instances": _i(399),
        "scanners": []},
    "a-transport-change-that-silently-changes-the-payload": {
        "instances": _i(489, rules=(426,)),
        "scanners": []},
    "the-empty-collection": {"instances": _i(118), "scanners": []},
    "an-error-swallowed": {"instances": _i(477, 501), "scanners": []},
    "success-assumed-exit-status-unchecked": {"instances": _i(328), "scanners": []},
    "partial-failure-leaves-inconsistent-state": {"instances": _i(181), "scanners": []},
    "order-assumed-on-unordered-data": {"instances": _i(252), "scanners": []},
    "external-input-trusted": {"instances": _i(246, 363, 368, rules=(374,)), "scanners": []},
    "toctou-check-then-act": {"instances": _i(422), "scanners": []},
    "non-idempotent-retry": {"instances": _i(184, 496, rules=(432,)), "scanners": []},
    "resource-leak-on-the-error-path": {"instances": _i(444), "scanners": []},
    "mutable-shared-or-default-state": {"instances": _i(303, 495, rules=(334, 431)), "scanners": []},
    "empty-versus-absent-conflated": {"instances": _i(195), "scanners": []},
    "regex-over-or-under-matching": {"instances": _i(49), "scanners": []},
    "flaky-by-time-or-randomness": {"instances": _i(349), "scanners": []},
    "assuming-a-single-result": {"instances": _i(438), "scanners": []},
    "cwd-or-script-location-path-assumption": {"instances": _i(108, 151), "scanners": []},
    "cleanup-missing-on-failure": {"instances": _i(373), "scanners": []},
    "a-guard-built-and-tested-that-nothing-invokes": {
        "instances": _i(1, 137, 143, 172, 182, 191, 279, 284, rules=(251,)), "scanners": []},
    "an-input-accepted-and-silently-ignored": {
        "instances": _i(60, 103, 215, 315, 329, rules=(355,)),
        "scanners": ["tests/test_json_everywhere.py::test_no_verb_ignores_json"]},
    "a-fact-recorded-without-its-context": {
        "instances": _i(266, 270, 281, 331, 341, 450, rules=(293, 356)), "scanners": []},
    "a-non-production-run-writes-live-state": {
        "instances": _i(29, 188, 290, 455, rules=(414,)), "scanners": []},
    "a-closed-table-fronting-an-open-set": {
        "instances": _i(213, 228, 245, 263, 298, 318, 379, 380, 387, rules=(379, 419)), "scanners": []},
    "state-is-whichever-row-came-last": {
        "instances": _i(225, 253, 254, 393, 399, rules=(382, 389)), "scanners": []},
    "a-proxy-checked-in-place-of-the-property": {
        "instances": _i(68, 101, 173, 196, 283, 322, 365), "scanners": []},
    "a-rule-change-leaves-old-decisions-standing": {
        "instances": _i(73, 230, 295, 301, rules=(333,)), "scanners": []},
    "one-default-tuned-for-one-member-applied-to-all": {
        "instances": _i(355, 401, 498), "scanners": []},
    "history-reconstructed-from-present-state": {
        "instances": _i(506, rules=(292,)), "scanners": []},
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
