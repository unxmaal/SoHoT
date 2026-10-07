"""Durable memory for the discovery loop. Issue #52.

Without this a sweep prints and forgets, so nothing compounds: every run
re-proposes what was already declined, and the precision of the extractor cannot
be measured because there is no record of what became of anything.

`proposals` is identity, `sightings` is the time axis, `verdicts` is what
happened. This package re-exports every name; the code lives in its modules. #484.
"""
from __future__ import annotations

# The old module's imports, which callers reach as ms.time, ms.paths and so on.
import json  # noqa: F401
import os  # noqa: F401
import re  # noqa: F401
import sqlite3  # noqa: F401
import time  # noqa: F401

from harness import paths, store  # noqa: F401

from harness.memory_store.schema import (ADOPT, FETCH, GIB, GITHUB, HUGGINGFACE,
    INSPECT, JUDGE, LADDER, MEASURE, REGISTRIES, SCHEMA_VERSION, SCREEN, TERMINAL,
    TIERS, VERDICTS, WAYPOINTS, _DDL, _columns)  # noqa: F401
from harness.memory_store.machines import (machine_row, recorded_facts,
    remember_machine, this_machine)  # noqa: F401
from harness.memory_store.cards import (CARD_COLUMNS, card_of, parents_of, set_card,
    with_lineage)  # noqa: F401
from harness.memory_store.sources import (record_source, source_row)  # noqa: F401
from harness.memory_store.benchmarks import (benchmarks, probe_summary,
    record_benchmark, record_probe, set_training, training)  # noqa: F401
from harness.memory_store.transitions import (IllegalTransition, REOPENS, RETEST,
    RETESTS, RETEST_AFTER_SECONDS, RETEST_TIERS, RETRACTION, _held,
    _migration_retraction, _schedule_retest, _write, decide, decide_or_skip, fold,
    retest_eligible, retract, state_audit, transition_refused)  # noqa: F401
from harness.memory_store.retests import (due_retests, recovered_false_negatives,
    reopen_due_retests, retest_counts)  # noqa: F401
from harness.memory_store.revisit import (_version_tuple, dangling_receipts,
    requeue_revisitable, resolved_run_paths, revisitable, until_for, until_met)  # noqa: F401
from harness.memory_store.proposals import (REJECTIONS, Seen, by_registry, by_source,
    export, extraction, judgeable, judgeable_total, latest, link, parents, pending,
    precision, ranked, record, recurrence, reject, retire_unlisted, set_lane,
    set_registry, set_size, settled, survivors, traverse)  # noqa: F401
from harness.memory_store.migrations.columns import (DEAD_COLUMNS, _add_card_facts,
    _add_edge_scores, _add_first_token, _add_machine_versions, _add_reasons,
    _add_result_split, _add_retest, _add_served_context, _add_sighting_machine,
    _add_state, _drop_column, drop_dead_columns, split_result_artifacts)  # noqa: F401
from harness.memory_store.migrations.prose import (_attribute_old_verdicts,
    _backfill_until, _let_a_revived_upstream_be_reconsidered,
    _lift_kind_and_age_out_of_prose, _lift_sizes_out_of_prose,
    _reopen_terminal_harness_and_limit_facts, backfill_card_facts, backfill_reasons,
    backfill_result_classes, backfill_sizes, card_from_description, lift_edge_scores,
    reason_audit, size_from_card, size_from_prose, size_sources,
    strip_machine_from_fetch_details)  # noqa: F401
from harness.memory_store.migrations.retractions import (_backfill_lanes,
    _canonical_lanes, _relane_from_the_card, _relane_the_laneless_from_lineage,
    _relane_the_laneless_from_the_card,
    _relane_the_settled_tasks, _reopen_architecture_gaps, _requeue_broken_matching,
    _requeue_diffusers_layout_gaps, _requeue_screens_of_missing_weights,
    _retract_harness_refusals, _retract_screens_with_no_evidence,
    _retract_verdicts_from_runs_that_never_ran, _retract_verdicts_with_no_control,
    _stated, _verdicts_name_a_candidate, _wrong_lane_requeues)  # noqa: F401
from harness.memory_store.migrations.identity import (_adopted_by_name,
    _backfill_registry, _backfill_state, _by_download, _candidate_from_receipt,
    _legacy_spec, _resolve_fakes, backfill_adoptions, backfill_candidates,
    backfill_retests, resolve_identity_leftovers)  # noqa: F401
from harness.memory_store.migrations.legacy import (LEGACY_FILES, _machine_fk_tables,
    attribute_sightings, import_discovery_state_json, import_human_verdicts_json,
    import_memory_limits_json, import_size_cache_lanes, merge_duplicate_machines)  # noqa: F401
from harness.memory_store.migrations import (MigrationReentered, _migrate,
    _migrate_steps, _refuse_reentry, _store_file, migrating)  # noqa: F401
from harness.memory_store.connection import (BUSY_TIMEOUT_SECONDS, LiveStoreRefused,
    ReadOnlyStore, _guard_live, _stored_schema, connect, db_path, lend, lent)  # noqa: F401
