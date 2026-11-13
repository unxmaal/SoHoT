"""Nightly mutation testing of the core modules, ratcheted against a pinned inventory (#492 F3, #1785).

gauntlet mutation --config tests.gauntlet.mutation:CONFIG run [--module M ...] [--pin] [--found FILE] [--jobs N]
gauntlet mutation --config tests.gauntlet.mutation:CONFIG pin --from FILE [FILE ...]
python -m tests.gauntlet.mutation changed [--base REF]
"""

import argparse
import sys
from pathlib import Path

from gauntlet.mutation import MutationConfig, functions_of

from harness import repo

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PIN_FILE = HERE / "mutation_survivors.json"

MODULES = {
    "harness/memory_store/transitions.py": [
        "tests/test_store_state.py", "tests/test_store_retest.py", "tests/test_harness_store_retraction.py",
        "tests/test_store_retract_screens.py", "tests/test_harness_memory_store.py",
        "tests/test_verdict_reasons.py", "tests/test_harness_store.py", "tests/test_rank_881.py",
        "tests/test_coherence_991.py", "tests/test_adopt_retest_1001.py", "tests/test_missing_package_1008.py",
        "tests/test_live_screen_blame_1021.py", "tests/test_whisper_group_1024.py", "tests/test_audio_env_1030.py", "tests/test_drafters_1039.py", "tests/test_plan_refusal_1047.py",
        "tests/test_cut_sites_1202.py"],
    "harness/reasons.py": [
        "tests/test_weedout_1439.py", "tests/test_gguf_first_911.py", "tests/test_verdict_reasons.py", "tests/test_refusal_shapes.py", "tests/test_screen_server_death.py",
        "tests/test_screen_evidence.py", "tests/test_harness_engines_repo_id.py",
        "tests/test_mps_backend_abort.py", "tests/test_timeouts_classed.py", "tests/test_agent_limits.py",
        "tests/test_served_ctx_limit.py", "tests/test_eval_budget.py", "tests/test_batch_lease_769.py",
        "tests/test_budget_ladder.py", "tests/test_knob_binding.py", "tests/test_screen_fair.py",
        "tests/test_new_lane_loop_faults.py", "tests/test_shared_store_703.py", "tests/test_ocr_lane.py",
        "tests/test_fetch_inspected_798.py", "tests/test_retrieval_lane.py",
        "tests/test_adopt_assumptions.py", "tests/test_cold_load.py", "tests/test_degenerate_955.py",
        "tests/test_load_log_953.py", "tests/test_runner_gap_until_950.py", "tests/test_deepen_993.py", "tests/test_missing_package_1008.py",
        "tests/test_diffusers_dtype_1013.py", "tests/test_live_screen_blame_1021.py", "tests/test_whisper_group_1024.py",
        "tests/test_runner_packages_1027.py", "tests/test_requires_backends_1031.py", "tests/test_audio_env_1030.py",
        "tests/test_tts_drop_1036.py", "tests/test_drafters_1039.py", "tests/test_plan_refusal_1047.py"],
    "harness/screen.py": [
        "tests/test_runner_gap_until_950.py", "tests/test_gguf_first_911.py", "tests/test_harness_screen.py", "tests/test_harness_screen_spec.py", "tests/test_screen_evidence.py",
        "tests/test_screen_server_death.py", "tests/test_screen_server_killer_1544.py", "tests/test_decide_lane.py", "tests/test_refusal_shapes.py",
        "tests/test_verdict_reasons.py", "tests/test_screen_case_fit.py", "tests/test_methods.py",
        "tests/test_ds4.py", "tests/test_screen_fair.py", "tests/test_gguf_route.py",
        "tests/test_harness_adopt_receipt.py", "tests/test_lane_coverage.py",
        "tests/test_loop_end_to_end.py", "tests/test_retrieval_lane.py", "tests/test_harness_lanes.py",
        "tests/test_liveness_705.py", "tests/test_runner_base_weights.py", "tests/test_ladder_seams.py",
        "tests/test_harness_lane_provenance.py", "tests/test_pii_lane.py", "tests/test_remote_code.py",
        "tests/test_ocr_lane.py", "tests/test_degenerate_955.py", "tests/test_load_log_953.py",
        "tests/test_screen_listing_984.py", "tests/test_missing_package_1008.py", "tests/test_diffusers_dtype_1013.py",
        "tests/test_live_screen_blame_1021.py", "tests/test_whisper_group_1024.py",
        "tests/test_requires_backends_1031.py", "tests/test_audio_env_1030.py", "tests/test_tts_drop_1036.py", "tests/test_drafters_1039.py", "tests/test_plan_refusal_1047.py",
        "tests/test_stt_screen_power_1007.py", "tests/test_staging_torch_1358.py",
        "tests/test_presence_960.py", "tests/test_limit_cuts_1087_harness_ps.py"],
    "harness/adopt.py": [
        "tests/test_adopt_retest_1001.py", "tests/test_harness_adopt.py", "tests/test_harness_adopt_receipt.py", "tests/test_adopt_by_spec.py",
        "tests/test_adoptions.py", "tests/test_adopt_cmd.py", "tests/test_human_verdicts.py",
        "tests/test_schema_lanes.py", "tests/test_holdout_power.py", "tests/test_power_budget.py",
        "tests/test_methods.py", "tests/test_adopt_scope.py", "tests/test_method_serving.py",
        "tests/test_resume_813.py", "tests/test_adopt_assumptions.py", "tests/test_lane_metric_validity.py",
        "tests/test_reverify.py", "tests/test_loop_end_to_end.py", "tests/test_candidates.py",
        "tests/test_claims_balanced_metric.py", "tests/test_gateway_switch.py", "tests/test_live_audit.py",
        "tests/test_shared_store_703.py", "tests/test_screen_evidence.py", "tests/test_harness_winners.py",
        "tests/test_lane_routes.py", "tests/test_remote_upstreams.py", "tests/test_deepen_993.py",
        "tests/test_lane_too_small_1049.py", "tests/test_lane_until_1053.py", "tests/test_reverify_lane_metric_733.py",
        "tests/test_adopt_effect_confirm_725.py", "tests/test_min_effect_1320.py",
        "tests/test_limit_cuts_1087_harness_ac.py", "tests/test_limit_cuts_1087_harness_ps.py",
        "tests/test_adopt_store_given_1673.py", "tests/test_adoption_state_1735.py"],
    "harness/serving.py": [
        "tests/test_harness_serving.py", "tests/test_lane_routes.py", "tests/test_gguf_route.py",
        "tests/test_schema_lanes.py", "tests/test_ds4.py", "tests/test_remote_upstreams.py",
        "tests/test_cold_load.py", "tests/test_slots_memory.py",
        "tests/test_liveness_705.py", "tests/test_mcp_delegate.py", "tests/test_context_store.py",
        "tests/test_nodes.py", "tests/test_trajectory_921.py", "tests/test_plan_refusal_1047.py"],
    "harness/router.py": [
        "tests/test_router_unload.py", "tests/test_lane_routes.py", "tests/test_router_swaps.py",
        "tests/test_cold_load.py", "tests/test_remote_upstreams.py", "tests/test_gguf_route.py",
        "tests/test_cut_sites_1202.py", "tests/test_router_phantoms_780.py", "tests/test_affine_queue_1617.py",
        "tests/test_gpu_lease_lock_1619.py", "tests/test_store_down_refuse_1648.py",
        "tests/test_gguf_aux_1674.py"],
}

# Test files that import a mutated module and are deliberately not run against its mutants:
# a constant or a type only, too slow, or crashes the forkserver (#596; test_mlx_backlog imports mlx, whose Metal
# thread segfaults a forked worker). A new importer goes in one or the other (#840).
LEFT_OUT = {
    "harness/memory_store/transitions.py": ("test_blame_audit.py", "test_live_audit.py", "test_lane_too_small_1049.py",
                                            "test_lane_until_1053.py", "test_loop_revisit_1055.py",
                                            "test_revisit_tier_1060.py", "test_revisitable_after_deploy_1361.py",
                                            "test_revisitable_met_1749.py", "test_site.py", "test_futility_lane_too_small_1452.py"),
    "harness/reasons.py": (
        "test_replay_budget_1822.py", "test_passed_over_class_1779.py", "test_owner_decline_1564.py", "test_runtime_trials_1474.py", "test_repo_repair_890.py", "test_agent_cut_call_1547.py", "test_craft_lane_1209.py", "test_staging_1244.py", "test_staging_torch_1358.py",
        "test_vision_engines_1282.py",
        "test_shots_check_1208.py", "test_node_drain_1815.py",
        "test_adopt_retest_1001.py", "test_attachment_tags_949.py", "test_canary_919.py",
        "test_chaos.py", "test_claims_lane.py", "test_gateway_key.py", "test_harness_checks_ocr.py",
        "test_harness_paired.py", "test_harness_screen.py", "test_harness_screen_spec.py",
        "test_holdout_power.py", "test_inspect_method_specs.py", "test_inspect_ratelimit.py",
        "test_knob_sweeps.py", "test_knobs.py", "test_loop_backpressure.py", "test_loop_namespace_974.py",
        "test_method_serving.py", "test_pii_lane.py",
        "test_power_budget.py", "test_quants_882.py", "test_repo_claude_905.py", "test_repo_doc_hunk_1107.py", "test_repo_lane.py", "test_repo_no_tools_1129.py", "test_runner_base_weights.py", "test_schema_lanes.py",
        "test_fetch_needs_1091.py", "test_planted_919.py", "test_trajectory_921.py", "test_unranked_weight_954.py", "test_inventory_heartbeat_972.py",
        "test_silent_truncation.py", "test_slots_memory.py", "test_store_downloads.py", "test_sweep_settle_1178.py", "test_sweep_lane_metric_1219.py", "test_sweep_fallback_metric_1230.py", "test_yield_stop_1127.py",
        "test_repo_causes_1170.py", "test_pool_full_retry_755.py", "test_engine_timeout_708.py", "test_reply_cap_1352.py",
        "test_engine_timeout_1256.py", "test_trocr_tokenizer_1025.py", "test_fetch_files_1040.py", "test_lane_too_small_1049.py",
        "test_lane_until_1053.py", "test_loop_revisit_1055.py", "test_revisit_tier_1060.py",
        "test_revisitable_after_deploy_1361.py", "test_revisitable_met_1749.py", "test_adopt_effect_confirm_725.py", "test_min_effect_1320.py", "test_technique_triage_993.py",
        "test_exam_price_1354.py", "test_limit_cuts_1087_evals.py", "test_limit_cuts_1087_harness_di.py",
        "test_futility_lane_too_small_1452.py", "test_sustained_warn_1482.py", "test_technique_kinds_1476.py",
        "test_engine_trials_1475.py", "test_screen_server_killer_1544.py", "test_mflux_second_repo_1546.py", "test_interactive_1561.py",
        "test_slot_plan_refusal_1651.py", "test_incumbent_silent_1656.py"),
    "harness/screen.py": (
        "test_replay_budget_1822.py", "test_passed_over_class_1779.py", "test_measure_gateway_1660.py", "test_attachment_tags_949.py", "test_lane_too_small_1049.py", "test_vision_engines_1282.py",
        "test_variants_947.py", "test_chaos.py", "test_claims_balanced_metric.py", "test_harness_engines_repo_id.py",
        "test_harness_report.py", "test_incumbent_lookup.py", "test_lane_metric_validity.py", "test_loop_backpressure.py",
        "test_canary_919.py", "test_mps_backend_abort.py", "test_new_lane_loop_faults.py", "test_rank_881.py",
        "test_remote_upstreams.py", "test_router_unload.py", "test_slots_memory.py", "test_store_card_facts.py",
        "test_store_state.py", "test_until_keys_928.py", "test_fetch_files_1040.py", "test_lane_heads_1084.py",
        "test_engine_timeout_708.py", "test_engine_timeout_1256.py",
        "test_served_readonly_1247.py", "test_adopt_effect_confirm_725.py",
        "test_confirm_resume_1357.py", "test_store_errors_1432.py", "test_canary_stt_1531.py",
        "test_mflux_second_repo_1546.py", "test_incumbent_silent_1656.py", "test_adoption_state_1735.py"),
    "harness/adopt.py": (
        "test_measure_gateway_1660.py", "test_canary_stt_1531.py", "test_technique_triage_993.py", "test_harness_paired.py", "test_reverify_case_sets_1496.py", "test_reverify_power_1504.py", "test_harness_report.py", "test_loop_circuit.py", "test_measure_budget.py",
        "test_over_budget_796.py", "test_planted_919.py", "test_projection_696.py", "test_rank_893.py", "test_router_unload.py",
        "test_store_state.py", "test_stt_screen_power_1007.py", "test_sweep_ceiling_806.py", "test_loop_revisit_1055.py",
        "test_incumbent_from_measurement_1110.py", "test_env_error_coverage_1116.py", "test_site.py",
        "test_repo_looks_1353.py", "test_confirm_resume_1357.py",
        "test_metric_order_717.py",
        "test_served_readonly_1247.py", "test_saturation_lane_metric_1267.py", "test_gate_direction_1302.py",
        "test_power_table_603.py", "test_store_errors_1432.py", "test_futility_lane_too_small_1452.py",
        "test_weedout_1439.py", "test_adopt_dry_run_1548.py", "test_residency_sim_1559.py", "test_incumbent_silent_1656.py",
        "test_lifecycle_stateful_1766.py"),
    "harness/serving.py": (
        "test_store_down_refuse_1648.py", "test_styx_batch_1689.py", "test_engine_build_1607.py", "test_install_env_1518.py", "test_runtime_trials_1474.py", "test_mlx_backlog.py", "test_runner_gap_until_950.py", "test_agent_limits.py", "test_claims_lane.py", "test_decide_lane.py",
        "test_delegate_resident.py", "test_delegations.py", "test_lane_probe_924.py", "test_machine_host.py",
        "test_machine_identity.py", "test_mlx_dead_912.py", "test_purpose_825.py", "test_usage_gateway.py",
        "test_vllm.py", "test_repo_failures_921.py", "test_presence_960.py", "test_limit_cuts_1087_harness_di.py",
        "test_limit_cuts_1087_harness_ps.py", "test_sustained_warn_1482.py", "test_interactive_1561.py",
        "test_interactive_node_1562.py", "test_lane_probe_node_1653.py", "test_pinned_incumbent_1578.py",
        "test_node_digest_1683.py"),
    "harness/router.py": (
        "test_delegate_resident.py", "test_machine_host.py", "test_router_ready_1012.py", "test_sweep_ceiling_806.py",
        "test_watchdog.py", "test_memory_warn_1082.py", "test_idle_unload_1157.py", "test_router_down_1181.py",
        "test_limit_cuts_1087_harness_ac.py", "test_sustained_warn_1482.py", "test_interactive_1561.py",
        "test_interactive_node_1562.py", "test_pinned_incumbent_1578.py", "test_tts_footprint_1671.py"),
}

# Tests that parse harness source, list the repo with git or run a serve script; under mutmut they fail unmutated.
READS_SOURCE = (
    "tests/test_verdict_reasons.py::test_every_production_verdict_says_why",
    "tests/test_cold_load.py::test_the_desktop_idle_sleep_is_a_site_the_knob_inventory_sees",
    "tests/test_harness_lanes.py::test_every_measurable_modality_is_a_named_lane",
    "tests/test_harness_lanes.py::test_every_named_lane_has_cases_to_measure_it",
    "tests/test_harness_lanes.py::test_a_generated_lane_is_still_absent_from_the_tree",
    "tests/test_served_ctx_limit.py::test_the_inventory_sees_table_keys_with_hyphens",
    "tests/test_timeouts_classed.py::test_no_timeout_is_raised_without_its_class",
    "tests/test_slots_memory.py::test_the_router_is_started_with_the_models_max_its_plan_was_sized_for",
    "tests/test_context_store.py::test_the_router_reads_its_contexts_from_the_preset_not_one_ctx_size",
)


def _env(tree):
    return {"LOCALHARNESS_HOME": tree / ".lh-home", "HF_HOME": tree / ".hf-home"}


CONFIG = MutationConfig(
    root=REPO, modules=MODULES, pin_file=PIN_FILE, left_out=LEFT_OUT, deselect=READS_SOURCE,
    source_paths=("harness",), also_copy=("evals", "scripts", "gateway", "deploy", "voice", "tools", "docs", "Makefile"),
    uv_groups=("mutation", "mcp"), python="3.12", timeout_constant=60.0, env=_env,
    env_dirs=("LOCALHARNESS_HOME", "HF_HOME"), lister=repo.publishable,
)


def touched_functions(old, new, hunks):
    """The functions mutmut mutates (Cls.fn for a method) that a diff of one module changes or adds."""
    from tests.gauntlet import covmap
    names, out = set(functions_of(new)), set()
    for q in covmap.touched(old, new, hunks).funcs:
        parts = q.split(".")
        out.update(next(([".".join(parts[:i])] for i in range(len(parts), 0, -1) if ".".join(parts[:i]) in names), []))
    return sorted(out)


def changed(base, root=REPO):
    """{module: functions} this branch changes since its merge base with base, for a pull request's mutation run (#1666)."""
    from tests.gauntlet import scope
    diffs = scope.diff_of(list(MODULES), scope.merge_base(base, root), "HEAD", root)
    return {m: fns for m, (old, new, hs) in sorted(diffs.items()) if (fns := touched_functions(old, new, hs))}


def cmd_changed(a):
    for m, fns in changed(a.base).items():
        print(f"{m}\t{' '.join(fns)}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tests.gauntlet.mutation")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("changed", help="print each mutated module and the functions this branch changes, tab-separated")
    c.add_argument("--base", default="origin/main")
    c.set_defaults(fn=cmd_changed)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
