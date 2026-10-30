# Reverify Specification

## Purpose
A served model is measured once, when it is adopted. Reverify queues a normal job to run each wanted lane's served model again when a runtime it uses moves, when it has gone too long without a working run here, or when real use regressed after the lane's alias moved; it settles each re-run from the run its job stored and flags the lane, and it never changes what a lane serves. The verify pass (`harness/verify.py`) is the plainer sibling: it plans a run of each lane's own default where nothing has measured the lane here, and reads a verdict from the receipt.

## Requirements

### Requirement: Every wanted, unparked lane with a served model takes part
`reverify.served` SHALL list each lane in `lanes.WANTED` that is not parked and serves a model on this machine: the adopted spec (`adopt.current`) when there is one, else the typed default resolved through `screen.candidate_for`. A measured adoption SHALL be re-run beside its incumbent unless the incumbent is the served spec or a reference; a by-hand adoption SHALL be re-run alone. The lookup MUST NOT write to the store; the candidate row a re-run names is created when it is queued.

#### Scenario: Every lane takes part
- **WHEN** a dry-run check covers every lane
- **THEN** the planned lanes are exactly the wanted lanes that are not parked
Test: tests/test_reverify.py::test_every_wanted_lane_with_a_served_model_takes_part

#### Scenario: A typed default runs under the id the lane serves
- **WHEN** the code lane has no adoption and its stored pass was recorded under the default's old nickname
- **THEN** the queued job names the id the lane serves (`cli.DEFAULT_CODE_MODEL`)
Test: tests/test_reverify.py::test_a_runtime_upgrade_since_the_last_pass_queues_one_reverify

#### Scenario: A measured adoption
- **WHEN** the lane's served model was adopted by measurement over an incumbent
- **THEN** the job's `--candidates` lists the served spec, then the incumbent
Test: tests/test_reverify.py::test_a_measured_adoption_is_re_run_beside_its_incumbent

#### Scenario: A by-hand adoption
- **WHEN** the served model was adopted by hand
- **THEN** the job's `--candidates` lists the served spec alone
Test: tests/test_reverify.py::test_a_by_hand_adoption_is_re_run_alone

#### Scenario: A reference or identical incumbent
- **WHEN** a measured adoption's incumbent is a reference model or the same spec as the served one
- **THEN** no incumbent is re-run beside it
Test: untested

#### Scenario: The lookup on a read-only store
- **WHEN** `served` runs on a store opened `mode=ro`
- **THEN** it returns the same lanes, specs and incumbents as on a writable store, and writes nothing
Test: tests/test_served_readonly_1247.py::test_served_answers_every_lane_on_a_read_only_store

#### Scenario: The queued re-run creates the candidate row
- **WHEN** the served spec has no candidates row and a trigger fires
- **THEN** the lookup reports no candidate id, and queuing creates the row the reverification names
Test: tests/test_served_readonly_1247.py::test_a_queued_reverify_creates_the_row_the_lookup_did_not

### Requirement: The baseline is the newest working, unflagged run here
The baseline SHALL be the newest measure-tier run on this machine in which the served candidate worked and which no flagged reverification settled on. Worked MUST mean a case passed, or the lane's metric shows the model working where none passed (`screen.working`), never exact-case pass bits alone.

#### Scenario: The last working run, not the newest
- **WHEN** a passing run is followed by a newer run that passed nothing
- **THEN** version changes are read against the passing run
Test: tests/test_reverify.py::test_the_comparison_is_against_the_last_passing_run_not_the_newest

#### Scenario: A run that passed nothing
- **WHEN** the only run of the served model passed no case on a pass-bit lane
- **THEN** there is no baseline and the age trigger says there is no passing run on this machine
Test: tests/test_reverify.py::test_a_run_that_passed_nothing_is_not_a_pass

#### Scenario: Another machine's run
- **WHEN** the only passing run was recorded on another machine
- **THEN** it is not a baseline here
Test: tests/test_reverify.py::test_another_machines_pass_does_not_count_here

#### Scenario: A lane metric shows the model working
- **WHEN** a decide run has no exact-case pass but its fields are mostly right
- **THEN** it is the baseline, and a re-run like it settles passed with its `decide_accuracy` in the detail
Test: tests/test_reverify_lane_metric_733.py::test_a_decide_run_with_no_exact_case_but_right_fields_is_a_baseline_and_a_pass

#### Scenario: A flagged re-run is not the next baseline
- **WHEN** a re-run settled regressed
- **THEN** the baseline stays the earlier passing run
Test: tests/test_reverify.py::test_a_regressed_run_is_not_the_next_baseline

### Requirement: A runtime the lane uses moved since the baseline
The versions trigger SHALL fire for each version key the lane's spec runs through (`runtimes_for`, plus `macos`) that the baseline's environment and this machine both record and that differ, and for each runtime or model file whose bytes changed since the baseline recorded the spec's content identity. A key missing on either side is unknown, not a change. Text lanes MUST watch the runtimes of the engine `serving.engine_for` names, every text runtime when it names none, and a lane no table names MUST watch every watched runtime.

#### Scenario: A runtime upgrade
- **WHEN** `mlx-lm` on this machine differs from the baseline's recorded version
- **THEN** one job is queued with trigger `versions` naming the old and new versions
Test: tests/test_reverify.py::test_a_runtime_upgrade_since_the_last_pass_queues_one_reverify

#### Scenario: A runtime the lane does not use
- **WHEN** only `mflux` moved and the lane is code on mlx
- **THEN** nothing is queued
Test: tests/test_reverify.py::test_a_runtime_the_lane_does_not_use_is_not_a_trigger

#### Scenario: A version the old run did not record
- **WHEN** the baseline's environment lacks a key this machine records
- **THEN** that key is not a change and nothing is queued
Test: tests/test_reverify.py::test_a_version_the_old_run_did_not_record_is_unknown_not_a_change

#### Scenario: A macOS upgrade
- **WHEN** this machine's macOS version differs from the baseline's
- **THEN** the trigger reads `macos <old> -> <new>`
Test: tests/test_reverify.py::test_a_macos_upgrade_is_a_trigger

#### Scenario: A ds4 spec
- **WHEN** the served spec runs on ds4
- **THEN** `ds4` is the first watched runtime
Test: tests/test_ds4.py::test_a_ds4_run_is_reverified_when_ds4_changes

#### Scenario: A vLLM spec
- **WHEN** the served spec runs on vLLM
- **THEN** `vllm-mlx` is watched and `mlx-lm` is not
Test: tests/test_vllm.py::test_a_vllm_spec_is_stale_when_vllm_changes

#### Scenario: An engine nothing names
- **WHEN** the gateway config names no engine for the served spec
- **THEN** every text runtime set is watched
Test: tests/test_remote_upstreams.py::test_reverify_watches_every_text_runtime_for_an_unknown_engine

#### Scenario: A lane no table names
- **WHEN** a lane is neither text, decide nor in the lane runtime table
- **THEN** every runtime `machine.WATCHED` lists is watched, with `llama.cpp` and `macos`
Test: tests/test_reverify.py::test_a_lane_no_table_names_watches_every_runtime

#### Scenario: An image spec
- **WHEN** the image lane serves an mflux spec, or a diffusers spec
- **THEN** mflux and mlx are watched for the first, diffusers and torch for the second
Test: untested

#### Scenario: Model bytes moved
- **WHEN** the served model file was rewritten since the baseline recorded its identity
- **THEN** the versions trigger names the file whose bytes changed
Test: tests/test_incumbent_reuse_1094.py::test_reverify_names_a_model_whose_bytes_moved

### Requirement: A served model with no recent working run is due
The age trigger SHALL fire when there is no baseline (no working run on this machine) or the baseline is older than the lane's threshold, `days_for(lane)`: the meta key `reverify_days:<lane>`, else `DEFAULT_DAYS`. `set_days` MUST refuse a threshold that is not above zero.

#### Scenario: An old pass
- **WHEN** the baseline is older than the default threshold
- **THEN** the trigger reads `last passed <n> days ago`
Test: tests/test_reverify.py::test_a_pass_older_than_seven_days_is_due

#### Scenario: A recent pass
- **WHEN** the baseline is inside the threshold and nothing else moved
- **THEN** nothing is queued
Test: tests/test_reverify.py::test_a_pass_inside_seven_days_is_not

#### Scenario: A per-lane threshold
- **WHEN** one lane's threshold is set below its baseline's age
- **THEN** that lane is due and other lanes keep `DEFAULT_DAYS`
Test: tests/test_reverify.py::test_the_age_is_configurable_per_lane

#### Scenario: No working run here
- **WHEN** a lane has never worked on this machine
- **THEN** it is queued with `no passing run on this machine`
Test: tests/test_reverify.py::test_a_thin_lane_with_no_passing_run_here_is_queued

#### Scenario: A threshold of zero or less
- **WHEN** `set_days` is given zero or a negative number
- **THEN** it raises a ValueError and stores nothing
Test: untested

#### Scenario: An unreadable stored threshold
- **WHEN** the lane's meta value is not a number
- **THEN** `days_for` returns `DEFAULT_DAYS`
Test: untested

### Requirement: Real use regressed after the lane's alias moved
The usage trigger SHALL fire when `usage.regressions` reports a regression on the lane's newest gateway switch, unless a reverification of the same candidate was queued after that switch. A usage read that raises MUST NOT fire the trigger.

#### Scenario: Errors rise after a switch
- **WHEN** the gateway error rate after the lane's newest switch is well above the rate before it
- **THEN** a job is queued with trigger `usage` naming the error rate
Test: tests/test_reverify.py::test_a_real_use_regression_after_a_switch_queues_a_reverify

#### Scenario: Within noise
- **WHEN** errors after the switch are within noise
- **THEN** nothing is queued
Test: tests/test_reverify.py::test_real_use_within_noise_is_not_a_trigger

#### Scenario: Already re-run since the switch
- **WHEN** a re-run was queued after the switch and has settled
- **THEN** the same regression does not queue another
Test: tests/test_reverify.py::test_a_usage_regression_already_reverified_since_the_switch_does_not_requeue

#### Scenario: The usage read fails
- **WHEN** `usage.around_switches` raises
- **THEN** the usage trigger does not fire and the check goes on
Test: untested

### Requirement: A fired trigger queues one low-priority job and runs nothing inline
`check` SHALL queue, for each lane with a trigger and no reason to skip, one `evals.run` job through `workqueue.add` with `requested_by` `REQUESTED_BY`, priority `PRIORITY`, this machine's id and the checkout as cwd, and record a `reverifications` row. A lane with an unsettled re-run SHALL be skipped as already queued. The job MUST run at the baseline's repeat and split, with the uv groups its lane's cases need and the gateway the served spec routes to. A dry run SHALL plan and judge and write nothing.

#### Scenario: Nothing moved
- **WHEN** versions match and the pass is fresh
- **THEN** nothing is queued and the plan says `nothing moved`
Test: tests/test_reverify.py::test_the_same_versions_and_a_fresh_pass_queue_nothing

#### Scenario: A second check
- **WHEN** a check runs while the lane's job is still pending
- **THEN** no second job is queued and the plan says `already queued as job`
Test: tests/test_reverify.py::test_a_second_check_does_not_queue_a_second_job

#### Scenario: The queued job
- **WHEN** a trigger fires
- **THEN** the job is a command with negative priority, this machine's id and a title starting `reverify <lane>`, and no subprocess runs during the check
Test: tests/test_reverify.py::test_the_job_is_low_priority_on_this_machine_and_nothing_runs_inline

#### Scenario: The job's cwd
- **WHEN** the check is called from another directory
- **THEN** the job's cwd is the checkout (`paths.REPO`)
Test: tests/test_reverify.py::test_the_job_runs_in_this_checkout_wherever_soh_was_called

#### Scenario: A dry run
- **WHEN** a check runs with `dry_run`
- **THEN** it reports the triggers, queues nothing and writes no reverifications row
Test: tests/test_reverify.py::test_a_dry_run_says_what_it_would_queue_and_writes_nothing

#### Scenario: The baseline's repeat and split
- **WHEN** the baseline ran at a repeat above one on the holdout split
- **THEN** the job's argv carries the same `--repeat` and `--split`
Test: tests/test_reverify.py::test_the_rerun_runs_at_the_baseline_repeat_and_split

#### Scenario: An image re-run needs the metrics group
- **WHEN** the image lane's cases include a staging check
- **THEN** the job's launcher carries the metrics uv group
Test: tests/test_staging_torch_1358.py::test_every_evals_run_launch_of_the_image_lane_carries_the_metrics_group

#### Scenario: A repo re-run is queued without a screen
- **WHEN** a repo exam is added with `requested_by` a re-measuring planner
- **THEN** the queue accepts it with no repo screen result
Test: tests/test_repo_looks_1353.py::test_a_knob_sweep_or_reverify_of_a_measured_model_is_queued_without_a_screen

#### Scenario: A spec routed to another gateway
- **WHEN** `screen.routed_gateway` names a gateway for the served spec
- **THEN** the job's argv carries `--gateway` with it
Test: untested

#### Scenario: The check records this machine
- **WHEN** a check that is not a dry run starts
- **THEN** this machine's facts are remembered in the store before planning
Test: untested

### Requirement: A re-run settles from the run its job stored
`settle` SHALL judge every unsettled reverification whose job is no longer pending or running, across all lanes whatever lane the check names, from the newest run stamped with that job's id, and write the outcome, reason, failure class, detail and run id. The outcome SHALL be `passed`, `failed`, `regressed`, `unrun` or `cancelled`. A re-run in which the served candidate did not work SHALL be `failed` with the reason of the most common failure class, unless that reason is `harness`, which MUST make it `unrun`, never a verdict on the model. A job that stored no run, or a run with no row for the served candidate, SHALL be `unrun`.

#### Scenario: The re-run passes
- **WHEN** the job is done and its run passes like the baseline
- **THEN** the re-run settles `passed`, no second job is queued and the trigger no longer fires
Test: tests/test_reverify.py::test_a_rerun_that_passes_settles_passed_and_clears_the_trigger

#### Scenario: The re-run fails
- **WHEN** the run passes nothing and its failures are timeouts
- **THEN** the outcome is `failed` with reason `limit` and failure class `timeout`
Test: tests/test_reverify.py::test_a_rerun_that_fails_records_reason_and_failure_class

#### Scenario: A decide re-run gets every field wrong
- **WHEN** a decide re-run scores no field right
- **THEN** it settles `failed`
Test: tests/test_reverify_lane_metric_733.py::test_a_decide_rerun_that_gets_every_field_wrong_still_fails

#### Scenario: An stt re-run with no perfect clip
- **WHEN** no clip is word-perfect but the word error rate is what it was
- **THEN** it settles `passed`, not `failed`
Test: tests/test_reverify_lane_metric_733.py::test_an_stt_rerun_with_no_word_perfect_clip_but_a_plausible_wer_is_not_failed

#### Scenario: The job stored no run
- **WHEN** the job failed with no run stamped with its id
- **THEN** the outcome is `unrun`, reason `harness`, the detail says it stored no run, and the lane is flagged
Test: tests/test_reverify.py::test_a_job_that_stored_no_run_is_flagged_as_unrun_not_as_a_model_failure

#### Scenario: The gateway refused every case
- **WHEN** every row failed `refused_by_gateway`
- **THEN** the outcome is `unrun` with that failure class
Test: tests/test_reverify.py::test_a_rerun_the_gateway_refused_is_unrun_not_failed

#### Scenario: The run has no row for the served spec
- **WHEN** the job's run holds rows for other candidates only
- **THEN** the outcome is `unrun` naming the run and the spec
Test: untested

#### Scenario: A paused job
- **WHEN** the job's state is `paused` and it stored a partial run
- **THEN** the re-run is settled from that partial run like a finished one
Test: untested

#### Scenario: Settling ignores the lane filter
- **WHEN** a check names one lane and another lane's re-run has finished
- **THEN** the other lane's re-run is settled too
Test: untested

### Requirement: A cancelled re-run is not a verdict on the model
A re-run whose job row is gone, or whose job is recorded `cancelled` and stored no run, SHALL settle `cancelled` with reason `harness` and SHALL NOT flag the lane. A cancelled job that stored a run is judged on that run.

#### Scenario: A pending job is cancelled
- **WHEN** the pending re-run job is cancelled and its row is kept as `cancelled`
- **THEN** the reverification settles `cancelled` and the lane is not flagged
Test: tests/test_reverify.py::test_a_cancelled_job_is_not_a_verdict_on_the_model

#### Scenario: The job row is gone
- **WHEN** the job row was deleted, so the reverification's job id is null
- **THEN** it settles `cancelled`, saying the job was cancelled before it ran
Test: untested

#### Scenario: A cancelled job that stored a run
- **WHEN** a running re-run is cancelled after its run was stored
- **THEN** the run is judged like any other
Test: untested

### Requirement: A loss beyond the paired noise is a regression
When the re-run worked and has a baseline, `judge` SHALL pair the served candidate against itself across the two runs by base case and repeat, on the lane's metric (`winners.PRIMARY`), or per stratum at the lane's weights for a stratified lane, and SHALL settle `regressed` when more draws were lost than gained at `adopt.ALPHA` or below. Timeouts and harness failures MUST be neither lost nor gained, and repeats MUST shrink by the design effect. A pairing the cells refuse SHALL settle `unrun`. When an incumbent was re-run beside it and now beats it at `adopt.ALPHA`, the re-run SHALL settle `regressed` naming the incumbent.

#### Scenario: Beyond the noise
- **WHEN** the re-run loses most cases its baseline passed
- **THEN** it settles `regressed`, reason `candidate`, with the lost and gained counts in the detail
Test: tests/test_reverify.py::test_a_regression_beyond_the_paired_noise_is_flagged

#### Scenario: Within the noise
- **WHEN** the re-run loses a couple of cases
- **THEN** it settles `passed`
Test: tests/test_reverify.py::test_a_drop_within_the_paired_noise_is_not_a_regression

#### Scenario: Repeated cases
- **WHEN** baseline and re-run both ran repeats and the re-run loses most draws
- **THEN** it settles `regressed` with every lost draw counted
Test: tests/test_reverify.py::test_a_repeated_rerun_that_regresses_on_most_cases_is_flagged

#### Scenario: Deterministic failures across repeats
- **WHEN** two cases fail on every repeat
- **THEN** the design effect counts them as two cases and the re-run settles `passed`
Test: tests/test_reverify.py::test_two_deterministic_failures_at_repeat_3_are_not_a_regression

#### Scenario: Another repeat than the baseline
- **WHEN** the re-run ran each case once against a repeated baseline
- **THEN** the cells refuse the pairing and the re-run settles `unrun` naming the repeat
Test: tests/test_reverify.py::test_a_rerun_at_another_repeat_than_its_baseline_is_not_a_pass

#### Scenario: Field accuracy drops at an equal exact count
- **WHEN** a decide re-run keeps its exact-case count but loses field accuracy on most cases
- **THEN** it settles `regressed` on `decide_accuracy`, reason `candidate`, class `content_failed`
Test: tests/test_reverify_lane_metric_733.py::test_a_decide_rerun_that_holds_its_exact_count_but_loses_field_accuracy_regresses

#### Scenario: Exact cases lost, accuracy gained
- **WHEN** a decide re-run loses exact cases but gains as many per case on accuracy
- **THEN** it settles `passed`
Test: tests/test_reverify_lane_metric_733.py::test_losing_exact_cases_while_gaining_more_accuracy_elsewhere_is_not_a_regression

#### Scenario: Word error rate doubles
- **WHEN** an stt re-run passes as many clips with twice the word error rate
- **THEN** it settles `regressed` on `wer`
Test: tests/test_reverify_lane_metric_733.py::test_an_stt_rerun_whose_wer_doubles_at_an_equal_pass_count_regresses

#### Scenario: A stratified lane
- **WHEN** a claims re-run loses every recall case and gains as many expect-empty cases
- **THEN** pairing at the lane's stratum weights settles it `regressed`
Test: tests/test_reverify_lane_metric_733.py::test_a_claims_rerun_pairs_per_stratum_at_the_lane_weights

#### Scenario: Stratum weighting rounds against the claim
- **WHEN** the weighted gained count is fractional
- **THEN** it rounds toward no regression and the re-run settles `passed`
Test: tests/test_reverify_lane_metric_733.py::test_the_stratum_weighting_rounds_against_the_regression_claim

#### Scenario: A timeout is unjudged
- **WHEN** a case the baseline passed times out in the re-run
- **THEN** it is unjudged and not among the lost rows
Test: tests/test_timeouts_classed.py::test_reverify_pairing_leaves_a_timeout_out_of_lost

#### Scenario: Shuffled repeats
- **WHEN** the re-run's repeats arrive in another order, some timing out
- **THEN** they pair by base case and repeat, and the timeouts and harness errors stay unjudged
Test: tests/test_harness_paired.py::test_repeats_pair_by_base_case_and_shrink_while_timeouts_stay_unjudged

#### Scenario: The incumbent now beats the served model
- **WHEN** the incumbent re-run beside the served model wins by more than the noise
- **THEN** the re-run settles `regressed` naming the incumbent
Test: tests/test_reverify.py::test_an_incumbent_that_now_beats_the_served_model_is_flagged

#### Scenario: The incumbent wins on the lane metric
- **WHEN** served and incumbent tie on exact cases and the incumbent is better on `decide_accuracy`
- **THEN** the re-run settles `regressed` naming the incumbent
Test: tests/test_reverify_lane_metric_733.py::test_an_incumbent_better_on_decide_accuracy_at_equal_exact_counts_is_flagged

#### Scenario: A pass-bit lane's detail
- **WHEN** a code re-run passes every case
- **THEN** the detail reads `<spec> passed <n> of <n>` with no metric
Test: tests/test_reverify_lane_metric_733.py::test_the_stored_verdict_shape_is_unchanged_for_a_pass_bit_lane

#### Scenario: No baseline to pair with
- **WHEN** the re-run worked and the reverification has no baseline run
- **THEN** no self-pairing is made and the re-run settles `passed` unless the incumbent beats it
Test: untested

### Requirement: A flag never swaps the served model
A lane whose newest settled re-run is `failed`, `regressed` or `unrun` SHALL be flagged (`flags`), and the served model MUST NOT change. A flagged lane SHALL NOT be queued again until its age threshold has passed since the re-run settled.

#### Scenario: Flagged and kept
- **WHEN** a re-run settles `failed`
- **THEN** the adoption is unchanged, the lane is flagged, and the next check skips it as flagged
Test: tests/test_reverify.py::test_a_flagged_lane_keeps_its_served_model_and_is_not_requeued

#### Scenario: Tried again after the threshold
- **WHEN** the lane's threshold has passed since the failed re-run settled
- **THEN** a second job is queued
Test: tests/test_reverify.py::test_a_flagged_lane_is_tried_again_after_its_age_threshold

### Requirement: The report shows flags and stale lanes
`report.lanes_state` SHALL carry each lane's newest settled re-run and whether it is flagged, and SHALL call a lane stale when its newest measure run here is older than the lane's threshold; `soh report` SHALL print each flagged lane with its outcome and detail.

#### Scenario: A flagged lane in the report
- **WHEN** the code lane's re-run failed and another lane's threshold changed
- **THEN** code is flagged with its re-run outcome, the other lane is not, and the lane rows say `re-verify failed`
Test: tests/test_reverify.py::test_the_report_flags_the_lane_and_uses_the_lane_threshold

#### Scenario: Stale by the lane's threshold
- **WHEN** the lane's newest run is older than its threshold, then the threshold is raised past it
- **THEN** the lane is stale, then not stale
Test: tests/test_reverify.py::test_the_report_lists_lanes_whose_last_run_is_older_than_their_threshold

#### Scenario: `soh report` names the flagged lane
- **WHEN** the report state flags code as regressed
- **THEN** stdout names code, its served model, the outcome and detail, and no unflagged lane
Test: tests/test_reverify.py::test_soh_report_names_the_flagged_lane

### Requirement: `soh reverify` and the discover loop run the check
`soh reverify` SHALL run the check (optionally for one `--lane`, optionally `--dry-run`), print what it settled, planned and queued and each flagged lane, and emit the same as JSON; `--days` SHALL set one lane's threshold and MUST be refused without `--lane`. The discover loop's spend step SHALL run the check after the retests, never as a dry run. The verb's gateway purpose SHALL be `eval`.

#### Scenario: A dry run as JSON
- **WHEN** `soh reverify --lane web --dry-run --json` runs
- **THEN** it exits 0 with `dry_run` true, plans only web with its triggers, and queues nothing
Test: tests/test_reverify.py::test_soh_reverify_dry_run_json

#### Scenario: Setting a threshold
- **WHEN** `soh reverify --lane web --days` is given a number of days
- **THEN** that lane's threshold reads back as that number
Test: tests/test_reverify.py::test_soh_reverify_sets_a_lane_threshold

#### Scenario: A threshold with no lane
- **WHEN** `--days` is given without `--lane`
- **THEN** the command exits nonzero
Test: tests/test_reverify.py::test_soh_reverify_days_needs_a_lane

#### Scenario: The loop runs the check
- **WHEN** the discover loop's reverify step runs
- **THEN** it calls the check without `dry_run`
Test: tests/test_reverify.py::test_the_discover_loop_runs_the_check

#### Scenario: After the retests
- **WHEN** the loop spends
- **THEN** the reverify step runs after the retests step
Test: untested

#### Scenario: Gateway purpose
- **WHEN** `soh reverify` runs
- **THEN** its gateway requests carry purpose `eval`
Test: tests/test_purpose_825.py::test_a_cli_verb_sets_its_purpose

### Requirement: The verify pass plans each lane's own default where nothing measured it
`verify.plan` SHALL plan a run of each lane's own served default that is unverified (no receipt here) or, unless told otherwise, stale, or every lane when forced, cheapest first by `COST_S` with skipped tasks last. It MUST skip a lane naming no default, and a parked lane or a lane in `DELIBERATE` unless the lane was named; a skipped task MUST carry no command. The command SHALL be `evals.run` on the lane with the default's candidate, the uv groups its cases need, and `--gateway` only when the default routes to another gateway.

#### Scenario: No receipt
- **WHEN** a lane has no receipt on this machine
- **THEN** it is planned with why `no receipt on this machine`
Test: tests/test_harness_verify.py::test_a_lane_with_no_receipt_is_planned

#### Scenario: Stale
- **WHEN** a lane is stale
- **THEN** it is planned and says how many days ago it was measured
Test: tests/test_harness_verify.py::test_a_stale_lane_is_planned_and_says_how_old

#### Scenario: Fresh
- **WHEN** a lane is neither unverified nor stale
- **THEN** it is not planned
Test: tests/test_harness_verify.py::test_a_fresh_lane_is_left_alone

#### Scenario: Forced
- **WHEN** the plan is forced
- **THEN** a fresh lane is planned
Test: tests/test_harness_verify.py::test_every_lane_can_be_forced

#### Scenario: Cheapest first
- **WHEN** two lanes are planned
- **THEN** the cheaper by `COST_S` comes first
Test: tests/test_harness_verify.py::test_cheapest_first

#### Scenario: Video only by name
- **WHEN** video is unverified and not named
- **THEN** it is skipped with a hint naming `--lane video` and carries no command
Test: tests/test_harness_verify.py::test_video_is_never_started_without_being_asked_for_by_name

#### Scenario: Naming video
- **WHEN** the plan names video
- **THEN** it is planned with a command
Test: tests/test_harness_verify.py::test_naming_video_opts_into_it

#### Scenario: No default
- **WHEN** a lane serves nothing
- **THEN** it is skipped with `the lane names no default to run` and no command
Test: tests/test_harness_verify.py::test_a_lane_naming_no_default_is_skipped_rather_than_run

#### Scenario: The lane's own default
- **WHEN** a lane is planned
- **THEN** the command is `evals.run --modality <lane>` naming the default
Test: tests/test_harness_verify.py::test_the_command_runs_the_lanes_own_default

#### Scenario: A gateway alias
- **WHEN** the default is a gateway alias
- **THEN** the command carries no `--gateway`
Test: tests/test_harness_verify.py::test_an_alias_lane_is_not_routed_upstream

#### Scenario: A whisper default
- **WHEN** the stt default runs in the whisper group
- **THEN** the planned command starts with that group's environment
Test: tests/test_whisper_group_1024.py::test_every_evals_run_launch_of_a_whisper_spec_uses_the_group_env

#### Scenario: A parked lane
- **WHEN** a parked lane is planned, even forced
- **THEN** it is skipped with `parked:` and carries no command
Test: tests/test_harness_verify.py::test_a_parked_lane_is_never_planned_automatically

#### Scenario: A parked lane with no receipt, forced
- **WHEN** a parked lane with no age is forced
- **THEN** the plan says `no receipt on this machine` and skips it as parked
Test: tests/test_harness_verify.py::test_all_plans_a_parked_lane_with_no_receipt_without_crashing

#### Scenario: Naming a parked lane
- **WHEN** the plan names a parked lane
- **THEN** it is planned with a command
Test: untested

### Requirement: The verify verdict reads the receipt alone
`verify.verdict` SHALL call a lane `works` when its default passed every case, `partial` when it passed some, and `broken` when it passed none, had no cases, or the receipt has no summary. `verify.summarise` SHALL give one line per candidate with passes, median seconds and metrics.

#### Scenario: Every case passes
- **WHEN** the receipt passes every case
- **THEN** the verdict is `works`
Test: tests/test_harness_verify.py::test_a_default_that_passes_everything_works

#### Scenario: No case passes
- **WHEN** the receipt passes no case
- **THEN** the verdict is `broken`
Test: tests/test_harness_verify.py::test_a_default_that_passes_nothing_is_broken

#### Scenario: Some cases pass
- **WHEN** the receipt passes some cases
- **THEN** the verdict is `partial`
Test: tests/test_harness_verify.py::test_a_default_that_passes_some_is_partial_not_broken

#### Scenario: No receipt or no cases
- **WHEN** there is no summary, or it counts no cases
- **THEN** the verdict is `broken`
Test: tests/test_harness_verify.py::test_no_receipt_and_no_cases_are_both_broken

#### Scenario: The summary line
- **WHEN** a receipt has passes, a median and a metric
- **THEN** the line names the candidate, its passes and the metric
Test: tests/test_harness_verify.py::test_the_summary_line_names_the_candidate_and_its_metric
