"""Migration helpers that add, split and drop columns."""
from __future__ import annotations

import json
import sqlite3

from harness import store
from harness.memory_store.cards import CARD_COLUMNS
from harness.memory_store.schema import _columns


#: Columns nothing reads: (table, column). #419.
DEAD_COLUMNS = (("proposals", "consumes"), ("proposals", "produces"),
                ("verdicts", "issue"), ("verdicts", "attaches_to"))


def drop_dead_columns(conn) -> dict:
    """Keep what the dead columns held, then drop them. #419.

    verdicts.issue folds into detail; verdicts.attaches_to fills an empty
    proposals.attaches_to. A store whose SQLite cannot drop a column keeps it.
    """
    got = {"issue_folded": 0, "attaches_lifted": 0, "dropped": [], "kept": []}
    if "issue" in _columns(conn, "verdicts"):
        for r in conn.execute("SELECT id, detail, issue FROM verdicts "
                              "WHERE issue IS NOT NULL").fetchall():
            tag = f"#{r['issue']}"
            if tag not in (r["detail"] or ""):
                detail = f"{r['detail']} ({tag})" if r["detail"] else tag
                conn.execute("UPDATE verdicts SET detail = ? WHERE id = ?",
                             (detail, r["id"]))
            got["issue_folded"] += 1
    if "attaches_to" in _columns(conn, "verdicts"):
        got["attaches_lifted"] = conn.execute(
            "UPDATE proposals SET attaches_to = (SELECT v.attaches_to FROM "
            "verdicts v WHERE v.proposal_id = proposals.id AND v.attaches_to <> '' "
            "ORDER BY v.id DESC LIMIT 1) WHERE attaches_to = '' AND id IN "
            "(SELECT proposal_id FROM verdicts WHERE attaches_to <> '')").rowcount
    for table, col in DEAD_COLUMNS:
        dropped = _drop_column(conn, table, col)
        if dropped is not None:
            got["dropped" if dropped else "kept"].append(f"{table}.{col}")
    return got


def _drop_column(conn, table: str, col: str) -> bool | None:
    """Drop one column; None if absent, False if this SQLite cannot drop it."""
    if col not in _columns(conn, table):
        return None
    if store.backend() != store.POSTGRES and \
            sqlite3.sqlite_version_info < (3, 35, 0):
        return False
    conn.execute("SAVEPOINT drop_dead")
    try:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    except Exception:  # noqa: BLE001 - an older SQLite that cannot: keep it
        conn.execute("ROLLBACK TO drop_dead")
        ok = False
    else:
        ok = True
    conn.execute("RELEASE drop_dead")
    return ok


def _add_result_split(conn) -> None:
    """results.output and results.artifact_path, on an older store. #463."""
    for col in ("output", "artifact_path"):
        if col not in _columns(conn, "results"):
            conn.execute(f"ALTER TABLE results ADD COLUMN {col} TEXT")


def split_result_artifacts(conn) -> dict:
    """Split the old artifact column into output and artifact_path, then drop it. #463."""
    from harness import runs
    counts = runs.split_artifacts(conn)
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('artifact_split', ?)",
                 (json.dumps(counts, sort_keys=True),))
    _drop_column(conn, "results", "artifact")
    return counts


def _add_sighting_machine(conn) -> None:
    if "machine_id" not in _columns(conn, "sightings"):
        conn.execute("ALTER TABLE sightings ADD COLUMN machine_id "
                     "INTEGER REFERENCES machines(id)")


def _add_machine_versions(conn) -> None:
    if "versions" not in _columns(conn, "machines"):
        conn.execute("ALTER TABLE machines "
                     "ADD COLUMN versions TEXT NOT NULL DEFAULT '{}'")


def _add_first_token(conn) -> None:
    """The results' first-token timing columns, on an older store. #468."""
    for col, ddl in (("ttft_s", "REAL"), ("first_reasoning_s", "REAL"),
                     ("prefill_s", "REAL"), ("cold", "INTEGER")):
        if col not in _columns(conn, "results"):
            conn.execute(f"ALTER TABLE results ADD COLUMN {col} {ddl}")


def _add_attempts(conn) -> None:
    """results.attempts, the budget-ladder rungs a row tried, on an older store. #668."""
    if "attempts" not in _columns(conn, "results"):
        conn.execute("ALTER TABLE results ADD COLUMN attempts TEXT NOT NULL DEFAULT '[]'")


def _add_served_context(conn) -> None:
    """downloads' served-context columns, on an older store. #498."""
    for col, ddl in (("ctx", "INTEGER NOT NULL DEFAULT 0"),
                     ("ctx_trained", "INTEGER NOT NULL DEFAULT 0"),
                     ("kv_bytes_token", "INTEGER NOT NULL DEFAULT 0"),
                     ("ctx_slots", "INTEGER NOT NULL DEFAULT 0"),
                     ("ctx_why", "TEXT NOT NULL DEFAULT ''"), ("ctx_at", "REAL"),
                     ("kv_cap_bytes", "INTEGER NOT NULL DEFAULT 0"),
                     ("coresident_bytes", "INTEGER NOT NULL DEFAULT 0")):
        if col not in _columns(conn, "downloads"):
            conn.execute(f"ALTER TABLE downloads ADD COLUMN {col} {ddl}")


def _add_switch_outcome(conn) -> None:
    """gateway_switches.outcome and reason, on an older store. #522."""
    for col, ddl in (("outcome", "TEXT NOT NULL DEFAULT 'switched'"),
                     ("reason", "TEXT NOT NULL DEFAULT ''")):
        if col not in _columns(conn, "gateway_switches"):
            conn.execute(f"ALTER TABLE gateway_switches ADD COLUMN {col} {ddl}")


def _add_source_retired(conn) -> None:
    """sources.retired, on an older store. #625."""
    if "retired" not in _columns(conn, "sources"):
        conn.execute("ALTER TABLE sources ADD COLUMN retired TEXT NOT NULL DEFAULT ''")


def _add_category(conn) -> None:
    """proposals.category, on an older store. #576."""
    if "category" not in _columns(conn, "proposals"):
        conn.execute("ALTER TABLE proposals ADD COLUMN category TEXT NOT NULL DEFAULT ''")


def _add_code_facts(conn) -> None:
    """proposals.model_type and remote_code, on an older store. #567."""
    from harness.memory_store.cards import CODE_COLUMNS
    for col in CODE_COLUMNS:
        if col not in _columns(conn, "proposals"):
            conn.execute(f"ALTER TABLE proposals ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")


def _add_reasons(conn) -> None:
    """verdicts.reason and the results' failure class, on an older store. #408."""
    for table, col in (("verdicts", "reason"), ("results", "failure_class"),
                       ("results", "hit_limit")):
        if col not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} "
                         f"TEXT NOT NULL DEFAULT ''")


def _add_state(conn) -> None:
    """The state columns, on a store older than the DDL. #409."""
    for table, col, ddl in (
            ("proposals", "state", "TEXT NOT NULL DEFAULT ''"),
            ("proposals", "state_verdict_id", "INTEGER"),
            ("verdicts", "reopens", "INTEGER REFERENCES verdicts(id)"),
            ("verdicts", "reopen_kind", "TEXT NOT NULL DEFAULT ''")):
        if col not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def _add_retest(conn) -> None:
    """The retest columns, on a store older than the DDL. #431."""
    for col, ddl in (("retest_count", "INTEGER NOT NULL DEFAULT 0"),
                     ("next_retest_at", "REAL")):
        if col not in _columns(conn, "proposals"):
            conn.execute(f"ALTER TABLE proposals ADD COLUMN {col} {ddl}")


def _add_card_facts(conn) -> None:
    for col in CARD_COLUMNS:
        if col not in _columns(conn, "proposals"):
            default = "'[]'" if col == "card_tags" else "''"
            conn.execute(f"ALTER TABLE proposals ADD COLUMN {col} "
                         f"TEXT NOT NULL DEFAULT {default}")


def _add_edge_scores(conn) -> None:
    """edges.shared/crowd/score, on a store older than the DDL. #416."""
    for col, ddl in (("shared", "INTEGER"), ("crowd", "INTEGER"),
                     ("score", "REAL")):
        if col not in _columns(conn, "edges"):
            conn.execute(f"ALTER TABLE edges ADD COLUMN {col} {ddl}")


def _add_holdout_power(conn) -> None:
    """The holdout split and power columns on runs and verdicts, on an older store. #479."""
    for table, col, ddl in (("verdicts", "failure_class", "TEXT NOT NULL DEFAULT ''"),
                            ("verdicts", "split_version", "TEXT NOT NULL DEFAULT ''"),
                            ("verdicts", "power", "TEXT NOT NULL DEFAULT '{}'"),
                            ("runs", "split", "TEXT NOT NULL DEFAULT ''"),
                            ("runs", "split_version", "TEXT NOT NULL DEFAULT ''")):
        if col not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
