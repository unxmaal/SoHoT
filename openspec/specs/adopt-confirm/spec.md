# Adopt and Confirm Specification

## Purpose
The adopt tier decides whether a measured or hand-judged challenger replaces a lane's incumbent, confirms a holdout win on cases it was not decided on, records the verdict and any adoption, and resolves at call time which model each lane serves on each machine.

## Requirements

### Requirement: Metric gate first
The adopt tier SHALL adopt a challenger only when its summary row is better than the incumbent's on the lane's own metric, using the one project ordering rule (`winners.order_key`); speed or pass count alone SHALL NOT adopt.

#### Scenario: faster but worse on the lane metric
- **WHEN** a challenger is faster and passes as often but is worse on the lane's metric
- **THEN** `better()` is false and `decide()` does not adopt
Test: tests/test_harness_adopt.py::test_a_faster_candidate_that_loses_on_the_metric_is_not_adopted

#### Scenario: better on the metric without significance
- **WHEN** a challenger is better on the metric but its paired cells give p above alpha
- **THEN** the verdict is not adopted and its reason says the difference is not established
Test: tests/test_harness_adopt.py::test_a_better_metric_alone_is_not_enough

### Requirement: Paired gate on shared cases
After the metric gate the adopt tier SHALL require a paired, case-matched comparison of incumbent and challenger from one run, tested with the exact sign test (McNemar on discordant cells) at the level in force; with no paired rows, or no case shared, it MUST NOT adopt.

#### Scenario: a significant paired win adopts
- **WHEN** the challenger wins on the metric and gains 8 cells against 0 lost
- **THEN** the verdict adopts and its reason carries the p value
Test: tests/test_harness_adopt.py::test_a_significant_win_on_the_metric_is_adopted

#### Scenario: no paired rows
- **WHEN** `decide()` is given no rows
- **THEN** nothing is adopted
Test: tests/test_harness_adopt.py::test_without_paired_rows_nothing_is_adopted

#### Scenario: no case in common
- **WHEN** the two candidates' rows share no case
- **THEN** nothing is adopted and the reason says they share no case
Test: tests/test_harness_adopt.py::test_two_candidates_sharing_no_case_is_refused_not_called_a_tie

### Requirement: Gained must exceed lost
The adopt tier SHALL adopt from a paired comparison only when gained cells exceed lost cells, before any p value is read, both in the gate and in the confirmation.

#### Scenario: a tie or net loss with a metric win
- **WHEN** the metric gate passes but lost cells are greater than or equal to gained cells
- **THEN** the verdict is a loss saying the paired cells do not favour the challenger
Test: tests/test_harness_adopt.py::test_a_metric_win_whose_paired_cells_do_not_favour_it_is_a_loss

#### Scenario: many cells lost on the gate and the confirmation
- **WHEN** a challenger that the metric gate favours loses far more cells than it gains
- **THEN** `decide()` and `confirm()` both decline it as significantly worse, a candidate loss
Test: tests/test_gate_direction_1302.py::test_the_paired_gate_never_adopts_a_challenger_that_lost_more_cells_than_it_gained

### Requirement: Significantly worse is a candidate loss
When a challenger is not adopted and its lost cells exceed gained at p within alpha, the adopt tier SHALL record a candidate loss naming it significantly worse, whatever the plan's power, with rounding that goes against the claim of worse.

#### Scenario: twenty cells lost
- **WHEN** a challenger loses 20 cells against 0 gained
- **THEN** the reason contains "significantly worse: 20 lost against 0 gained"
Test: tests/test_harness_adopt.py::test_a_metric_win_that_lost_significantly_says_it_is_worse

#### Scenario: shrunk cells round against worse
- **WHEN** correlated repeats shrink 9 lost and 1 gained
- **THEN** `_worse` rounds lost down and gained up and does not call it worse
Test: tests/test_adopt_assumptions.py::test_worse_rounds_against_the_claim_that_the_challenger_is_worse

### Requirement: Correlated repeats counted as cases
The adopt tier SHALL divide gained and lost cells by the design effect 1+(r-1)*rho before the sign test, using the measured within-case correlation or an assumed rho of 1.0, rounding against the side the claim favours, and SHALL say so in the reason.

#### Scenario: the adopt gate rounds against the challenger
- **WHEN** rho 0.5 at repeat 2 shrinks 9 gained and 1 lost
- **THEN** the gate's p is 0.125
Test: tests/test_adopt_assumptions.py::test_the_adopt_gate_still_rounds_against_the_challenger

#### Scenario: a confirmation over repeats states the count
- **WHEN** a confirmation reads 20 gained cells from 10 cases at repeat 2 with rho unmeasured
- **THEN** the reason says 10 gained against 0 lost once correlated repeats are counted as cases, rho 1.00 assumed
Test: tests/test_adopt_effect_confirm_725.py::test_a_confirmation_over_correlated_repeats_says_how_it_counted_them

### Requirement: Alpha over the comparison count
The adopt tier SHALL test a challenger on a holdout at `alpha_for(tested)` = ALPHA (0.05) / (tested + 1), where tested counts the lane's earlier adopt verdicts on that holdout version other than inconclusive and lane_too_small ones, less any alpha spent on interim looks, and SHALL record the comparison count, the alpha used and any differing planned alpha in the verdict.

#### Scenario: the twentieth challenger
- **WHEN** 19 verdicts already exist on the holdout and the challenger gains 7 of 20 cases
- **THEN** it is not adopted, evidence has comparisons 20 and alpha 0.05/20, and the reason says "comparison 20"
Test: tests/test_adopt_assumptions.py::test_the_twentieth_challenger_on_one_holdout_faces_an_adjusted_alpha_and_says_so

#### Scenario: comparisons are per lane and holdout version
- **WHEN** three code verdicts and one svg verdict are recorded on one version
- **THEN** `comparisons("code", version)` is 3, another version is 0, and a recorded count is persisted in the verdict's power
Test: tests/test_adopt_assumptions.py::test_comparisons_count_the_lanes_verdicts_on_one_holdout_version

#### Scenario: a lane-size verdict is not a comparison
- **WHEN** a plan no run can decide is written as lane_too_small
- **THEN** `comparisons()` for that lane stays 0
Test: tests/test_lane_too_small_1049.py::test_measure_does_not_run_a_plan_that_cannot_decide

#### Scenario: a verdict lands mid-run
- **WHEN** the plan was made at one alpha and another verdict on the holdout landed before this one
- **THEN** evidence carries planned_alpha and the tested alpha, and the reason says so
Test: tests/test_adopt_assumptions.py::test_a_verdict_landing_mid_run_is_recorded_beside_the_alpha_the_plan_used

#### Scenario: interim looks spend alpha
- **WHEN** a paused paired run with a recorded look finishes and is decided
- **THEN** the verdict's stored alpha is below ALPHA
Test: tests/test_resume_813.py::test_a_finished_resume_spends_less_alpha_and_stores_planned_and_observed_seconds

### Requirement: Holdout decides and dev is reported
With a split the adopt tier SHALL run both gates on holdout rows only and report the dev comparison beside the verdict without gating on it; a lane too small to split SHALL use every case as its holdout and record the caveat.

#### Scenario: a dev-only win
- **WHEN** the challenger gains every dev cell and ties every holdout cell
- **THEN** it is not adopted and the reason reports the dev gain
Test: tests/test_holdout_power.py::test_a_win_on_dev_alone_is_not_adopted

#### Scenario: a holdout win
- **WHEN** the challenger gains 6 holdout cells against 0 lost
- **THEN** the gate adopts, the reason reports dev beside it, and evidence names the split version
Test: tests/test_holdout_power.py::test_a_win_on_holdout_is_adopted_and_dev_is_reported_beside_it

#### Scenario: a lane too small to split
- **WHEN** the split is too_small
- **THEN** the gate reads every case and the reason and evidence carry the too-small caveat
Test: tests/test_holdout_power.py::test_a_lane_too_small_adopts_on_all_cases_with_the_caveat_recorded

### Requirement: Power decides what a null means
With a power plan the adopt tier SHALL record a non-significant result as underpowered (declined, limit, retestable) when the plan's power is under its target, when the incumbent has no stored draws, or when the smallest detectable gain exceeds the lane's effect, and SHALL record it as a candidate loss only when the plan could see that effect.

#### Scenario: power under target
- **WHEN** the plan's power is below 0.8
- **THEN** the verdict is underpowered and its reason starts "underpowered"
Test: tests/test_holdout_power.py::test_an_underpowered_null_says_so

#### Scenario: no stored incumbent draws
- **WHEN** the plan is unmeasured
- **THEN** the null is underpowered and says the incumbent has no stored draws
Test: tests/test_adopt_assumptions.py::test_a_plan_with_no_incumbent_draws_is_unmeasured_and_its_null_underpowered

#### Scenario: detectable gain above the lane effect
- **WHEN** a powered plan's smallest detectable gain is above the lane's effect
- **THEN** the null is underpowered "not shown at +X" and is recorded with reason limit
Test: tests/test_adopt_assumptions.py::test_a_null_under_a_plan_for_a_bigger_effect_than_the_lane_cares_about_is_not_shown_and_retestable

#### Scenario: a powered null
- **WHEN** the plan could see the lane's effect and the gate is not significant
- **THEN** the verdict is a candidate loss with no failure class
Test: tests/test_holdout_power.py::test_a_powered_null_is_an_ordinary_loss

#### Scenario: the null names what it could see
- **WHEN** an underpowered null is recorded
- **THEN** its reason names the smallest gain the run could see at power 0.8
Test: tests/test_adopt_assumptions.py::test_an_underpowered_null_names_the_smallest_gain_the_run_could_see

### Requirement: Minimum effect worth a switch
The adopt tier SHALL power the gate for `effect_for(lane)` = max(lane rerun noise, MIN_EFFECT 0.10); a null that is a loss only because the floor exceeds the lane's noise SHALL carry `min_effect` evidence, and `record()` (never `decide()`) SHALL write an `adopt_min_effect` limit cut for it.

#### Scenario: noise under the floor
- **WHEN** a lane's registered noise is 0.05
- **THEN** its effect is 0.10
Test: tests/test_min_effect_1320.py::test_a_lane_whose_noise_effect_is_0_05_is_powered_at_the_floor

#### Scenario: a floor-only loss records a cut on record
- **WHEN** a null could see +0.08 on a lane with noise 0.05
- **THEN** the loss reason ends with the adopt_min_effect sentence, deciding alone writes no cut, and recording it writes one limit_cuts row and persists min_effect
Test: tests/test_min_effect_1320.py::test_a_null_that_only_the_floor_makes_a_loss_records_a_cut

#### Scenario: decide keeps the null's floor evidence
- **WHEN** `_null` returns min_effect evidence
- **THEN** `decide()` copies it into its own evidence beside the power plan
Test: tests/test_min_effect_1320.py::test_decide_carries_the_floor_evidence_from_its_null

### Requirement: Lane too small and undecidable plans
The adopt tier SHALL record a null on a holdout no repeat could power as lane_too_small (declined, limit) waiting on `cases:<lane>>N`, and SHALL write that verdict without running the pair when the plan has power 0 even at +1.00 per cell.

#### Scenario: a null on a too-small lane
- **WHEN** a null comes from a plan whose holdout needs more cases than the lane has
- **THEN** the verdict is lane_too_small with an until on the lane's case count
Test: tests/test_lane_too_small_1049.py::test_a_null_on_a_too_small_lane_names_both_sides_and_waits_on_that_lane

#### Scenario: a plan no run can decide
- **WHEN** `undecidable()` is given a plan whose max power is 0
- **THEN** it returns a lane_too_small verdict saying it was not run
Test: tests/test_lane_too_small_1049.py::test_a_plan_no_run_can_decide_is_a_verdict_written_without_running_it

### Requirement: Dev confirmation of a holdout win
A measured gate win SHALL serve only when its confirmation cells (dev rows, less cases the challenger's screen ran) are better on the lane metric with gained > lost at p within ALPHA (0.05, not divided by the comparison count); otherwise it SHALL be declined: a candidate loss when significantly worse, or when the cells were powered to see the lane's effect (the rule `decide()` applies to a null, with the cells planned as a holdout: the incumbent's draws on them at their repeat and ALPHA); only a null the cells could not see SHALL be underpowered, naming the smallest gain they could see. By-hand verdicts and losses SHALL pass through unchanged.

#### Scenario: dev confirms
- **WHEN** 10 dev cases show 8 gained against 0 lost
- **THEN** the verdict adopts with "confirmed on 10 dev case(s)" and confirm evidence
Test: tests/test_adopt_effect_confirm_725.py::test_a_holdout_win_whose_dev_cells_confirm_it_is_adopted

#### Scenario: dev too small to see the effect does not confirm, or shows it worse
- **WHEN** 10 dev cases show 3 gained against 1 lost, or 10 lost
- **THEN** the first is underpowered (power under 0.8 at the lane's +0.10) and the second a candidate loss, significantly worse
Test: tests/test_adopt_effect_confirm_725.py::test_a_holdout_win_that_dev_cells_too_few_to_see_it_do_not_confirm_is_underpowered

#### Scenario: dev powered to see the effect does not confirm
- **WHEN** 100 dev cases, powered at the lane's +0.10, show 2 gained against 1 lost
- **THEN** the verdict is a candidate loss (declined/candidate), "no gain of +0.08 or more", not underpowered
Test: tests/test_adopt_effect_confirm_725.py::test_a_holdout_win_that_dev_cells_powered_to_see_it_do_not_confirm_is_a_loss

#### Scenario: confirmation reads the lane metric
- **WHEN** pass bits and the lane metric disagree on dev
- **THEN** the confirmation follows the lane metric and keeps the evidence it was given
Test: tests/test_adopt_effect_confirm_725.py::test_the_confirmation_reads_the_lane_metric_and_keeps_the_evidence_it_was_given

#### Scenario: screened cases are excluded
- **WHEN** the challenger's screen ran 8 of the 10 dev cases
- **THEN** only the other 2 are confirmation cells
Test: tests/test_adopt_effect_confirm_725.py::test_cases_the_challenger_was_screened_on_are_not_confirmation_cells

#### Scenario: only a measured win is confirmed
- **WHEN** `confirm()` is given a by-hand win or a loss
- **THEN** it returns that verdict unchanged
Test: tests/test_adopt_effect_confirm_725.py::test_only_a_measured_gate_win_is_confirmed

#### Scenario: confirmation is tested at undivided alpha
- **WHEN** the holdout verdict faced alpha_for(tested) with tested above 0
- **THEN** the confirmation still tests dev at ALPHA
Test: tests/test_adopt_effect_confirm_725.py::test_the_confirmation_is_tested_at_undivided_alpha

### Requirement: CONFIRMING holds a win until a night run
When a measured gate win has no confirmation cells the adopt tier SHALL record it as `confirming` (declined, limit), write no adoption so the incumbent keeps serving, and queue one night confirmation job; a lane too small to split SHALL always be held in-run, and the night run of it SHALL use every case.

#### Scenario: no dev rows ran
- **WHEN** a holdout win has only holdout rows
- **THEN** it is confirming, recorded declined/limit, no adoption row exists, and one night job `adopt --confirm <vid>` is queued once
Test: tests/test_adopt_effect_confirm_725.py::test_a_holdout_win_with_no_dev_rows_is_held_and_queues_a_night_confirmation

#### Scenario: a too-small lane in-run and fresh
- **WHEN** a too-small split is confirmed in-run, then on a fresh run
- **THEN** in-run there are no cells; the fresh run uses every case less screened ones
Test: tests/test_adopt_effect_confirm_725.py::test_confirmation_cells_come_from_dev_and_a_fresh_run_of_a_lane_too_small_to_split

### Requirement: Queueing a confirmation
`queue_confirmation` SHALL add `python -m harness.cli adopt --confirm VID` to the given store's work queue with requested_by "adopt", the repo as cwd, the night gate set and not_before at tonight's night start (or a given start), unless the same argv is already pending or running in a job other than the one this process runs in.

#### Scenario: the job's shape
- **WHEN** a confirming verdict is queued
- **THEN** the argv, title, cwd, requested_by and not_before match, no other store is opened, and a finished job does not block a new one
Test: tests/test_adopt_effect_confirm_725.py::test_the_confirmation_job_is_the_adopt_command_and_lands_in_the_given_store

#### Scenario: a job does not count itself
- **WHEN** the running confirmation job queues its own continuation with a start time
- **THEN** a new job is added at that start with the night gate, while another process sees the running job and queues nothing
Test: tests/test_adopt_effect_confirm_725.py::test_a_confirmation_job_does_not_count_itself_and_a_continuation_starts_when_named

### Requirement: The confirmation job decides or records nothing
`soh adopt --confirm VID` SHALL act only on a verdict that is still confirming and still its proposal's state verdict, and only while the lane serves the incumbent the hold named; it SHALL then run the pair on `--split dev` (every case for a too-small lane) at the stored repeat, confirm with fresh cells, and record the adoption or the decline.

#### Scenario: dev confirms at night
- **WHEN** the night run gains 9 dev cases
- **THEN** it ran `--split dev` with the stored pair, records outcome measured and writes an adoption
Test: tests/test_adopt_effect_confirm_725.py::test_the_confirmation_job_adopts_when_dev_confirms_the_win

#### Scenario: dev shows it worse at night
- **WHEN** the night run loses every dev case
- **THEN** it records declined/candidate and no adoption
Test: tests/test_adopt_effect_confirm_725.py::test_the_confirmation_job_declines_when_dev_shows_the_challenger_worse

#### Scenario: the incumbent changed
- **WHEN** the lane now serves a different model than the hold named
- **THEN** nothing runs, no verdict is written, and it says the lane no longer serves the held incumbent
Test: tests/test_adopt_effect_confirm_725.py::test_a_confirmation_against_a_changed_incumbent_records_nothing

#### Scenario: the verdict is no longer held
- **WHEN** the verdict is not confirming or a newer verdict is the proposal's state
- **THEN** it prints that there is nothing to confirm and returns 0
Test: untested

#### Scenario: a crash
- **WHEN** the confirmation eval exits non-zero other than paused
- **THEN** it returns 1 and queues nothing
Test: tests/test_confirm_resume_1357.py::test_a_crashed_confirmation_still_fails_and_queues_nothing

### Requirement: Confirmation resume, pause and continuation
The confirmation job SHALL resume the newest unfinished `*-confirm-<lane>` run of the same pair, repeat and split; record from a finished run of that exam newer than the hold, on the current split version, that no verdict was read from; start fresh when a resume is refused as another exam; and on a pause SHALL record no verdict, queue its continuation for the next night, and exit with the paused code (75).

#### Scenario: pause then resume through the queue
- **WHEN** a confirmation pauses after 8 cells inside a queue job
- **THEN** the job ends paused with rc 75 and no verdict, a continuation is queued for later, and that job resumes the same dir, runs only the rest and records the adoption
Test: tests/test_confirm_resume_1357.py::test_a_paused_confirmation_is_paused_queues_its_continuation_and_the_next_job_resumes_it

#### Scenario: which dir is resumed
- **WHEN** paused dirs exist for another pair, another split, another lane, and a done one
- **THEN** none is resumed, and of two matching paused dirs the newer is chosen
Test: tests/test_confirm_resume_1357.py::test_only_an_unfinished_confirm_dir_for_the_same_pair_and_exam_is_resumed

#### Scenario: a resume refused as another exam
- **WHEN** the resumed eval exits stale
- **THEN** it says "starting fresh", reruns in a new dir and records the verdict
Test: tests/test_confirm_resume_1357.py::test_a_resume_refused_as_another_exam_starts_fresh

#### Scenario: a run finished outside the job
- **WHEN** a matching dir is done with a stored run and no verdict on it
- **THEN** the verdict is recorded from its receipt without a rerun
Test: tests/test_confirm_resume_1357.py::test_a_finished_confirm_run_with_no_verdict_is_recorded_from_its_receipt_without_a_rerun

#### Scenario: a finished run that must not be reused
- **WHEN** a done dir was already judged, predates the hold, or names another split version
- **THEN** it is not reused
Test: tests/test_confirm_resume_1357.py::test_a_finished_confirm_run_already_judged_older_than_the_hold_or_of_another_exam_is_not_reused

### Requirement: Paired measure pauses and resumes
`soh adopt --lane L --challenger X` SHALL run incumbent and challenger in one paired eval in a named run directory; when the run pauses at its slice, or is killed at its deadline, it SHALL take an interim look, save a paused_runs row with no verdict and exit with the paused code (75), as a paused confirmation does, so a queue job running it is recorded paused; the discover loop SHALL count a paused pair as neither failed nor done; and the next measure of the pair SHALL resume the same directory at the same repeat.

#### Scenario: paused at the slice
- **WHEN** the paired eval stops at its stop time
- **THEN** `_measure` returns 75, a paused row with one look is saved and no adopt verdict is written
Test: tests/test_resume_813.py::test_a_run_paused_at_its_slice_is_recorded_with_progress_and_a_look

#### Scenario: the adopt command exits paused
- **WHEN** `soh adopt --lane code --challenger X` pauses
- **THEN** it returns 75 and a paused row is saved
Test: tests/test_resume_813.py::test_a_paused_adopt_command_exits_75_as_a_paused_confirmation_does

#### Scenario: a sweep is not failed by a pause
- **WHEN** the loop measures a pair that pauses and one that fails
- **THEN** only the failed one is a failed step
Test: tests/test_resume_813.py::test_a_sweep_counts_a_paused_pair_as_neither_failed_nor_done

#### Scenario: a deadline kill
- **WHEN** the eval is stopped at its deadline
- **THEN** it is a pause (75), not a verdict
Test: tests/test_resume_813.py::test_a_deadline_kill_is_a_pause_not_a_verdict

#### Scenario: the next measure resumes
- **WHEN** the pair is measured again
- **THEN** it passes --resume with the same --out and --repeat
Test: tests/test_resume_813.py::test_the_next_measure_resumes_the_same_run_and_counts_the_sweep

### Requirement: Measure refuses what cannot be concluded
Before deciding, the paired measure SHALL write no adopt verdict when the lane has no incumbent, when the challenger is already the lane's default, when the incumbent passed nothing (unless taken from measurement), when every challenger row never reached a model (it stays queued), or when an unscreened repo challenger lacks a surviving repo screen.

#### Scenario: no incumbent
- **WHEN** the lane has no typed or adopted default
- **THEN** nothing is measured
Test: tests/test_harness_adopt.py::test_a_lane_with_no_incumbent_measures_nothing

#### Scenario: the incumbent against itself
- **WHEN** the challenger's spec is the lane's default
- **THEN** it is settled as already the lane's default, not declined
Test: tests/test_harness_adopt_receipt.py::test_the_incumbent_is_not_measured_against_itself

#### Scenario: a control that passed nothing
- **WHEN** the incumbent passed 0 cases
- **THEN** no verdict is recorded
Test: tests/test_harness_adopt_receipt.py::test_a_control_that_passed_nothing_blocks_any_verdict

#### Scenario: a wholly refused challenger
- **WHEN** every challenger row is a harness refusal
- **THEN** it is requeued at screen, not declined
Test: tests/test_harness_adopt_receipt.py::test_a_wholly_refused_challenger_is_requeued_not_declined

#### Scenario: an unscreened repo challenger
- **WHEN** a repo adopt names a challenger with no surviving repo screen and no --unscreened
- **THEN** it is refused before any run
Test: tests/test_repo_looks_1353.py::test_a_repo_adopt_for_an_unscreened_challenger_is_refused_before_any_run

### Requirement: Recording a verdict
`record()` SHALL write every verdict on the candidate that ran at tier adopt (outcome measured for an adoption, else the class's outcome and reason, defaulting to declined/candidate, with underpowered, inconclusive, lane_too_small and confirming as limit), persist failure class, split version and power evidence, refuse a spec no runner takes, and write an adoptions row only when the verdict adopts.

#### Scenario: outcome and reason mapping
- **WHEN** a verdict carries no class, underpowered, inconclusive, timeout or crashed
- **THEN** `outcome_of` gives declined/candidate, declined/limit (three) and broken/candidate, and measured with the same reason when adopted
Test: tests/test_harness_adopt.py::test_a_loss_is_the_candidate_s_unless_its_class_says_the_gate_could_not_tell

#### Scenario: a loss is recorded
- **WHEN** a losing verdict is recorded
- **THEN** a declined adopt verdict exists and no adoption
Test: tests/test_harness_adopt.py::test_a_loss_is_recorded_too

#### Scenario: evidence persisted
- **WHEN** an underpowered verdict with split and plan is recorded
- **THEN** the row has failure_class underpowered, reason limit, the split version and the plan's power
Test: tests/test_holdout_power.py::test_the_verdict_row_carries_the_split_version_and_the_power

#### Scenario: a spec no runner takes
- **WHEN** the spec is not runnable
- **THEN** `record()` raises ValueError
Test: tests/test_candidates.py::test_a_label_that_is_no_runnable_spec_is_refused

#### Scenario: an adoption row
- **WHEN** a winning verdict is recorded
- **THEN** one adoptions row names lane, candidate, incumbent, verdict, how measured and the recording machine
Test: tests/test_adoptions.py::test_an_adoption_is_a_row_naming_lane_candidate_run_and_machine

### Requirement: Guards that refuse a win
`record()` SHALL turn a win into a non-adoption when the challenger or spec is a reference model (declined), when the spec is a negative control (declined, method verdicts suspect), or when the lane is a schema lane and the spec's engine cannot enforce the schema (queued/harness/refused_by_gateway), keeping the rest of the verdict.

#### Scenario: a reference model
- **WHEN** a hosted reference wins a lane by hand
- **THEN** no adoption serves it
Test: tests/test_adopt_by_spec.py::test_a_reference_model_is_never_adopted

#### Scenario: a negative control
- **WHEN** a control spec wins
- **THEN** it is declined with "negative control won" and the lane keeps its default
Test: tests/test_deepen_993.py::test_a_control_that_wins_is_never_adopted

#### Scenario: a schema lane off llama-server
- **WHEN** the decide lane adopts an MLX-served spec
- **THEN** nothing is adopted and the verdict is queued/harness/refused_by_gateway naming response_format
Test: tests/test_schema_lanes.py::test_a_schema_lane_never_adopts_what_cannot_enforce_its_schema

#### Scenario: a schema lane on llama-server
- **WHEN** the decide lane adopts a llama-server spec
- **THEN** it is adopted
Test: tests/test_schema_lanes.py::test_a_schema_lane_adopts_what_llama_server_serves

#### Scenario: the refusal keeps the verdict
- **WHEN** the schema guard refuses a win
- **THEN** lane, incumbent, challenger, how and evidence are kept
Test: tests/test_schema_lanes.py::test_a_refused_schema_win_keeps_every_field_of_the_verdict_it_refuses

### Requirement: Which machine an adoption serves
The adopt tier SHALL serve, per lane, the newest adoption whose machine is this machine (matched by fingerprint), or which was adopted with all_machines, or which names no machine; a measured adoption SHALL serve only the machine that recorded it, and a reference model is never served.

#### Scenario: measured serves its own machine
- **WHEN** a measured adoption is made on one machine
- **THEN** that machine serves it and another serves its typed default
Test: tests/test_adoptions.py::test_a_measured_adoption_serves_only_the_machine_that_measured_it

#### Scenario: one machine under another Python
- **WHEN** the same machine is seen under another Python build
- **THEN** it is one machine row and still serves its adoption
Test: tests/test_adoptions.py::test_the_same_machine_under_another_python_is_one_row

#### Scenario: newest wins
- **WHEN** two adoptions exist for one lane
- **THEN** the newer serves
Test: tests/test_adoptions.py::test_a_newer_adoption_replaces_the_older_for_the_lane

#### Scenario: local measurement over an older preference
- **WHEN** an all-machines by-hand adoption is followed by a measured one on one machine
- **THEN** that machine serves the measured one and others keep the by-hand one
Test: tests/test_adoptions.py::test_a_local_measurement_beats_an_older_remote_preference

#### Scenario: a reference row is never served
- **WHEN** a reference model has an adoptions row, even with no machine
- **THEN** the lane serves the previous local adoption
Test: tests/test_adoptions.py::test_a_reference_model_is_never_a_lane_default

#### Scenario: a row with no machine
- **WHEN** an adoption names no machine
- **THEN** every machine serves it
Test: untested

#### Scenario: disk keeps every machine's adoption
- **WHEN** one machine's adoption is read from another
- **THEN** `everywhere()` and the disk keep-list include it
Test: tests/test_adoptions.py::test_disk_keeps_every_machines_adoption

### Requirement: By-hand votes decide a judged lane
`decide_by_hand` SHALL adopt only a challenger that a strict majority of fully judged cases preferred; an unjudged lane SHALL NOT be a loss; fewer than MIN_VOTES (10) answers SHALL hold the adoption (record raises Held and writes nothing) unless forced, and a forced adoption is recorded as forced.

#### Scenario: unjudged is not a loss
- **WHEN** no case has enough answers
- **THEN** the verdict is not adopted and says "not judged"
Test: tests/test_human_verdicts.py::test_an_unjudged_lane_is_not_a_loss

#### Scenario: preferred and not preferred
- **WHEN** every case prefers one candidate
- **THEN** it is adopted as challenger, and as incumbent the other is told the incumbent was preferred
Test: tests/test_human_verdicts.py::test_the_preferred_candidate_is_adopted_and_the_other_is_not

#### Scenario: no preference
- **WHEN** every case is a tie
- **THEN** the incumbent stays
Test: tests/test_human_verdicts.py::test_no_preference_leaves_the_incumbent_in_place

#### Scenario: one win and ties
- **WHEN** one case is won and the rest tied
- **THEN** the lane is not carried
Test: tests/test_adopt_assumptions.py::test_one_win_and_three_ties_does_not_carry_the_lane

#### Scenario: a strict majority carries the lane
- **WHEN** both of two cases prefer the challenger
- **THEN** the lane verdict names the challenger
Test: tests/test_human_verdicts.py::test_a_strict_majority_of_cases_carries_the_lane

#### Scenario: a plurality that is not a majority
- **WHEN** of four cases the challenger wins two, the incumbent one and one is tied
- **THEN** there is no lane verdict, "won 2 of 4 case(s), not a majority"
Test: tests/test_human_verdicts.py::test_a_plurality_that_is_not_a_majority_does_not_carry_the_lane

#### Scenario: too few votes
- **WHEN** 9 votes prefer the challenger
- **THEN** the verdict is held, `record()` raises Held and no adopt verdict is written
Test: tests/test_adopt_scope.py::test_too_few_votes_is_held_not_lost

#### Scenario: forced
- **WHEN** --force adopts on 9 votes
- **THEN** the adoption row records votes 9, forced 1 and the agreement
Test: tests/test_adopt_scope.py::test_force_adopts_and_records_that_it_was_forced

#### Scenario: the minimum is a parameter
- **WHEN** min_votes is 3 and 3 votes agree
- **THEN** it adopts
Test: tests/test_adopt_scope.py::test_the_minimum_is_a_parameter

#### Scenario: measured is not gated on votes
- **WHEN** a measured win is recorded
- **THEN** it is adopted with no vote count
Test: tests/test_adopt_scope.py::test_a_measured_adoption_is_not_gated_on_votes

### Requirement: By-hand scope and fit
A by-hand adoption SHALL serve only the machine it was made on unless adopted with all_machines; every machine SHALL check `fit` before serving one, list a non-fitting one in `refused()` and serve the previous adoption; `record()` SHALL raise Held when it does not fit the adopting machine. Fit evidence SHALL be, in order, a passing stored run on that machine, the largest measured peak anywhere, the stored size, against the machine's ceiling; an unknown size is served and said.

#### Scenario: own machine only
- **WHEN** a by-hand adoption is read on another machine
- **THEN** that machine serves nothing from it
Test: tests/test_adopt_scope.py::test_a_by_hand_adoption_serves_only_the_machine_it_was_made_on

#### Scenario: all machines
- **WHEN** it is adopted with all_machines
- **THEN** the row records it and another machine serves it
Test: tests/test_adopt_scope.py::test_all_machines_is_explicit_and_recorded

#### Scenario: too big for a machine
- **WHEN** an all-machines adoption peaked over another machine's ceiling
- **THEN** that machine does not serve it and `refused()` names both sizes
Test: tests/test_adopt_scope.py::test_a_global_adoption_that_cannot_fit_a_machine_is_refused_there

#### Scenario: fallback to the previous adoption
- **WHEN** a refused all-machines adoption is newer than a fitting one
- **THEN** the fitting one serves
Test: tests/test_adopt_scope.py::test_a_refused_global_adoption_falls_back_to_the_previous_one

#### Scenario: never adopted where it cannot fit
- **WHEN** the adopting machine is too small
- **THEN** `record()` raises Held and no adoption is written
Test: tests/test_adopt_scope.py::test_a_model_that_cannot_fit_here_is_never_adopted_here

#### Scenario: a passing run here fits
- **WHEN** the model passed a run on this machine at a peak over the ceiling
- **THEN** it fits
Test: tests/test_adopt_scope.py::test_a_passing_run_on_the_machine_is_evidence_it_fits

#### Scenario: stored size over the ceiling
- **WHEN** only a stored size is known and it exceeds the ceiling
- **THEN** it is refused with "stored size"
Test: tests/test_adopt_scope.py::test_a_stored_size_over_the_ceiling_is_refused

#### Scenario: unknown size
- **WHEN** neither a size nor a peak is known
- **THEN** it is served and the fit says unknown
Test: tests/test_adopt_scope.py::test_an_unknown_size_is_served_but_said

### Requirement: Adoption cost and description
An adoption row SHALL carry the new and previous model's median seconds and peak on the recording machine, from that machine's runs only, with row counts; `describe()` SHALL name how it was made, its scope, votes and forced.

#### Scenario: cost against the previous model
- **WHEN** both models have runs on the machine
- **THEN** the cost names both medians and peaks and the ratio
Test: tests/test_adopt_scope.py::test_the_cost_delta_against_the_previous_adoption_is_recorded

#### Scenario: only this machine's runs
- **WHEN** the new model ran only elsewhere
- **THEN** the cost says there is no stored run here
Test: tests/test_adopt_scope.py::test_the_cost_reads_only_this_machines_runs

#### Scenario: describe
- **WHEN** a forced by-hand adoption is described
- **THEN** the text names by-hand, this machine, 12 votes and forced
Test: tests/test_adopt_scope.py::test_describe_names_scope_how_and_votes

### Requirement: What a lane serves is resolved at call time
`default_for` and `lane_defaults` SHALL return the lane's adoption on this machine, else the typed default, read from the store at each call, and SHALL never raise: a missing, locked or older store leaves the typed default. An adoption in a text lane SHALL refresh the gateway.

#### Scenario: typed until adopted
- **WHEN** nothing is adopted
- **THEN** the lane serves its typed constant
Test: tests/test_harness_adopt.py::test_a_lane_serves_its_typed_constant_until_something_is_adopted

#### Scenario: an adoption changes what is served
- **WHEN** a win is recorded
- **THEN** `default_for` returns the new spec
Test: tests/test_harness_adopt.py::test_an_adoption_changes_what_the_lane_serves

#### Scenario: an unreachable store
- **WHEN** the store raises
- **THEN** the typed constant is returned
Test: tests/test_harness_adopt.py::test_an_unreachable_store_leaves_the_lane_on_its_constant

#### Scenario: lane commands read it at call time
- **WHEN** a text lane adopts a spec after start-up
- **THEN** the lane command's model is the adopted spec
Test: tests/test_lane_routes.py::test_every_text_lane_resolves_its_adoption_at_call_time

#### Scenario: the gateway refresh
- **WHEN** a tts lane and then a code lane adopt
- **THEN** only the text lane restarts the gateway
Test: tests/test_lane_routes.py::test_an_adoption_restarts_the_gateway_for_text_lanes_only

### Requirement: Methods are adopted like models
A winning method spec SHALL get an adoptions row and be served through its base model's route, and a method verdict SHALL carry its calls and latency cost in its evidence, won or lost.

#### Scenario: a winning method
- **WHEN** `plan:<base>` wins the code lane
- **THEN** `current()` serves it and the verdict has no "not served" note
Test: tests/test_method_serving.py::test_a_winning_method_gets_an_adoption_row_and_no_not_served_note

#### Scenario: cost travels with the verdict
- **WHEN** `decide()` is given a method spec
- **THEN** evidence carries the method's cost and the reason its cost note
Test: untested

### Requirement: The soh adopt command
`soh adopt` SHALL route `--confirm VID` to the confirmation job, `--power` to the per-lane power table (planned at the holdout's adjusted alpha), `--from-measurement` to taking a never-passing typed incumbent's place from measurement, and `--lane` with `--challenger` to the paired measure; an unknown lane SHALL be refused before anything runs.

#### Scenario: a named challenger
- **WHEN** `soh adopt --lane svg --challenger q3-30b --repeat 3` runs
- **THEN** the paired measure gets that challenger and lane
Test: tests/test_adopt_cmd.py::test_adopt_hands_the_challenger_to_the_paired_measure

#### Scenario: an unknown lane
- **WHEN** the lane is not known
- **THEN** it exits 1 without measuring
Test: tests/test_adopt_cmd.py::test_an_unknown_lane_is_refused_before_anything_runs

#### Scenario: power at the adjusted alpha
- **WHEN** `soh adopt --power` runs on a holdout with earlier verdicts
- **THEN** each lane is planned at alpha_for of its comparison count
Test: tests/test_adopt_assumptions.py::test_adopt_power_plans_at_the_holdouts_adjusted_alpha

#### Scenario: a never-passing incumbent gives way to measurement
- **WHEN** a typed incumbent passed none of enough stored cases and a candidate covering the current exam gains enough
- **THEN** the take step returns an adopting verdict for that candidate
Test: tests/test_incumbent_from_measurement_1110.py::test_enough_gained_cases_take_the_incumbent_from_measurement

#### Scenario: the from-measurement flag
- **WHEN** `soh adopt --lane L --from-measurement` runs, with or without --dry-run
- **THEN** it takes the incumbent from measurement, or says why not, and --dry-run records nothing
Test: untested
