"""Knobs of the reports, audits and scanners soh runs for a person (#734)."""
from harness.knobs.base import _k

KNOBS = [
    _k("assertions_qualifier_window", ["harness/assertions.py:QUALIFIER_WINDOW"], [1, 2, 4],
       note="lines either side of a number its conditions may sit on before `soh assertions` calls it config-less (#159)"),
    _k("blame_second_n", ["harness/blame_audit.py:SECOND_N"], [10, 20, 40],
       note="terminal verdicts the blame audit draws for a second labeller to agree on (#918)"),
    _k("context_bands", ["harness/context_mistakes.py:BANDS"],
       [(0, 100_000, 200_000, 400_000, 600_000, 800_000), (0, 50_000, 100_000, 200_000), (0, 250_000, 500_000, 750_000)],
       note="lower edges, in input tokens, of the context bands `soh context --mistakes` tests (#1381)"),
    _k("context_big", ["harness/context_report.py:BIG"], [1000, 2000, 5000],
       note="estimated tokens past which a tool result counts toward `soh context`'s share over 2k (#828)"),
    _k("context_class_big", ["harness/context_class.py:BIG"], [500, 1000, 2000],
       note="estimated tokens from which a result counts in `soh context --by class`'s over-1k columns (#1333)"),
    _k("context_mistake_match_s", ["harness/context_mistakes.py:MATCH_S"], [30, 120, 600],
       note="seconds between a KB row and its add_negative/report_error result that join them as one event (#1381)"),
    _k("context_mistake_windows", ["harness/context_mistakes.py:WINDOWS"],
       [(10, 25, 50, 100), (5, 10, 20, 40), (25, 50, 100, 200)],
       note="messages after a compaction each window of `soh context --mistakes` spans (#1381)"),
    _k("dora_thin", ["harness/dora.py:THIN"], [2, 3, 5],
       note="incidents or lead times under which a DORA figure is marked thin; one incident once read as a median (#5bb56d5a)"),
    _k("knob_backlog_literal_letters", ["harness/knob_backlog.py:LITERAL_LETTERS"], [4, 8, 16],
       note="letters a reason template's literal text needs before stored reasons are matched to it, ranking the backlog (#1085)"),
]

NOT_GATING = {
    "harness/chaos.py:MIB": "bytes in a mebibyte (#492)",
    "harness/context_mistakes.py:_post->urllib.request.urlopen(timeout)": "network timeout of a by-hand KB read; "
                                                                          "it raises, it never drops a row (#1381)",
    "harness/funnel.py:OLDEST": "how many of a stage's longest waiters `soh funnel` names; every row is counted (#925)",
    "harness/migration_check.py:SHOWN": "failing rows a migration check's detail lists; the rest are counted (#478)",
}

NEVER_CUTS = {
    "harness/context_report.py:BIG": "which results the share-over-2k column counts; every result is counted (#828)",
    "harness/context_class.py:BIG": "which results the over-1k columns count; every result is counted (#1333)",
    "harness/context_mistakes.py:BANDS": "which band a message falls in; every message is in one band (#1381)",
    "harness/context_mistakes.py:MATCH_S": "which call a KB row joins; a row with none is counted and printed (#1381)",
    "harness/context_mistakes.py:WINDOWS": "which windows are tested; every message and event is counted (#1381)",
    "harness/dora.py:THIN": "marks a DORA figure thin; the figure is still computed and shown (#5bb56d5a)",
}
