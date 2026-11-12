"""This repo's gauntlet registry, handed to the pinned gauntlet package's ratchets and CLI (#492, #1785)."""

from pathlib import Path

from gauntlet.moves import MoveTable, reopens_by
from gauntlet.registry import Registry

from harness import deploy_state, download_state, exclusive, gateway_switch_state, job_state, paused, repo, sweeps
from tests.gauntlet import classes

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
# The agent lane's case repos are broken on purpose; they are inputs to a model, not code here.
NOT_PRODUCTION = ("tests/", "evals/cases/")
# Unbound hits pinned when the detectors landed; lower it as the backlog is bound.
BACKLOG_PIN = 857


# make precheck runs only these; the rest are whole-tree costly and stay in make check (#1832).
PRECHECK_DETECTORS = frozenset({
    "harness_verdicts", "duplicated_literals", "env_seams", "loopback_equality", "row_index_keys", "unreached_guards",
    "ignored_options", "closed_tables", "latest_row_state", "unguarded_transition", "member_defaults"})


def production(rel):
    return not rel.startswith(NOT_PRODUCTION)


MOVES = (
    MoveTable("harness/job_state.py:MOVES", job_state.MOVES, initial=(job_state.PENDING,),
              terminal=(job_state.DONE, job_state.FAILED, job_state.CANCELLED),
              states=(job_state.PENDING, job_state.RUNNING, job_state.DONE, job_state.FAILED, job_state.CANCELLED,
                      job_state.PAUSED)),
    MoveTable("harness/paused.py:MOVES", paused.MOVES, initial=(None,),
              terminal=(paused.STALE, paused.DONE, paused.DEFECT), states=paused.STATES),
    MoveTable("harness/deploy_state.py:MOVES", deploy_state.MOVES, initial=(deploy_state.NEW,),
              terminal=deploy_state.OUTCOMES, states=deploy_state.STAGES),
    MoveTable("harness/sweeps.py:MOVES", sweeps.MOVES, initial=(None,), terminal=sweeps.SETTLED + sweeps.FOUND,
              reopens=reopens_by(sweeps.MOVES, {sweeps.REFILED}), states=(sweeps.OPEN, *sweeps.SETTLED, *sweeps.FOUND)),
    MoveTable("harness/download_state.py:MOVES", download_state.MOVES, initial=(download_state.NONE,),
              terminal=(download_state.REMOVED,), states=download_state.STATES),
    MoveTable("harness/gateway_switch_state.py:MOVES", gateway_switch_state.MOVES, initial=(gateway_switch_state.NONE,),
              terminal=(gateway_switch_state.SERVING, gateway_switch_state.FAILED), states=gateway_switch_state.STATES),
    MoveTable("harness/exclusive.py:MOVES", exclusive.MOVES, initial=(exclusive.FREE,),
              states=(exclusive.FREE, exclusive.RESERVED, exclusive.LOADING, exclusive.LAPSED, exclusive.ABANDONED)),
)

MAINS = ("nodes", "install_env", "engine_smoke", "slot_probe", "router", "interactive")
EFFECTS = ("desktop", "monitor.post", "monitor.alert", "_gh", "gh_run", "_ssh", "spawn_switch", "pause_all", "urlopen",
           "ask_model", "install", "gather", "verify", "notify")
DETECTOR_CONFIG = {
    "unscoped_query": {"columns": ("machine_id",), "helpers": ("here", "_here", "all_machines", "machine_row")},
    "prose_match": {"fields": ("note", "detail", "reason", "why", "evidence", "outcome", "said", "summary", "subject"),
                    "migrations": ("harness/memory_store/migrations/",)},
    "empty_on_failure": {"choosers": ("backend",)},
    "unpaired_column": {"migrations": ("harness/memory_store/migrations/",),
                        "schema": ("harness/memory_store/schema.py",)},
    "one_sided_schema_check": {"versions": ("SCHEMA_VERSION", "code_schema", "_stored_schema", "_pg_schema"),
                               "phases": tuple(f"harness/{m}.py:__main__" for m in MAINS),
                               "markers": ("SMOKE_PHASE", "phase"), "skips": ("_skip",)},
    "effect_reachable": {"effects": EFFECTS,
                         "live": ("DEFAULT_HOME", "live_home", "runs_elsewhere", "is_live", "PYTEST_CURRENT_TEST",
                                  "FILE_ENV"),
                         "guarded": ("osascript", "terminal-notifier"), "spawners": ("spawn_group",)},
    "unchecked_order": {"effects": EFFECTS + ("httpx.post", "os.kill", "_run"),
                        "reads": ("backend", "home", "read_text", "exists"),
                        "entries": ("__main__",), "guard": ("env.guard", "env.ensure"),
                        "needs": ("HF_HOME", "models_dir", "hf_home", "free_bytes", "huggingface_hub"),
                        "pairs": {"LOCALHARNESS_HOME": ("LOCALHARNESS_STORE", "BACKEND_ENV", "pinned"),
                                  "ENV_VAR": ("LOCALHARNESS_STORE", "BACKEND_ENV", "pinned")}},
}


CR, OW, WT = ("two-durable-writes-with-no-repair-for-the-gap", "a-child-that-outlives-its-owner",
              "a-wait-with-no-deadline-owner-or-end-state")
SC, CA = "a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null", \
    "a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates"
FT, EF = "a-decision-read-back-out-of-a-sentence-the-code-wrote", "nothing-and-failed-return-the-same-value"
VS, OR = "a-deploy-runs-two-releases-at-once", "an-order-the-code-needs-but-does-not-check"
# Backlog rows an open #1748 high names: {issue: (class, site patterns)}; each pattern must still match a backlog row.
OPEN_ISSUES = {
    1759: (OW, (r"^harness/vllm\.py:served$",)),
    1762: (WT, (r"^harness/workqueue\.py:quiesce$",)),
    1763: (WT, (r"^harness/exclusive\.py:_beating\.keep$",)),
    1769: (SC, (r":null-scope$",)),
    1770: (SC, (r"^harness/adopt\.py:queue_confirmation:jobs$", r"^harness/workqueue\.py:_repend:jobs$")),
    1775: (CA, (r"^harness/nodes\.py:_record$",)),
    1777: (FT, (r"^harness/repo_gate\.py:(owed|verdict):detail$",)),
    1778: (FT, (r"^harness/watchdog\.py:(notified_since|overrun_stopped|wake):(outcome|evidence)$",)),
    1779: (FT, (r"^harness/rank\.py:passed_over:detail$",)),
    1781: (EF, (r"^harness/commands/(context|inventory|ledger)\.py:\w+:chooser$", r"^harness/otel\.py:_select:except$",
              r"^harness/trends\.py:(ledger|delegation)_rows:except$")),
    1782: (EF, (r"^harness/rank\.py:(incumbent_bases|passed_over):except$",)),
    1788: (VS, (r"^harness/workqueue\.py:stale_schema:one-sided$",)),
    1790: (VS, (r"^harness/(nodes|install_env|engine_smoke|slot_probe|router|interactive)\.py:__main__:both-phases$",)),
    1796: (OR, (r":default:",)),
}

MOVE_WAIVERS: dict = {}

REGISTRY = Registry(
    root=REPO,
    index=classes.INDEX, pending=classes.PENDING, unclassified=classes.UNCLASSIFIED,
    snapshot_file=HERE / "skill_classes.json", defects_file=HERE / "defects.json",
    backlog_file=HERE / "backlog.json", backlog_pin=BACKLOG_PIN,
    repo_slug="unxmaal/SoHoT",
    production=production,
    code_paths=r"^(?:harness/|scripts/|evals/(?!cases/))",
    files=repo.publishable,
    moves=MOVES,
    move_waivers=MOVE_WAIVERS,
    detector_config=DETECTOR_CONFIG,
)
