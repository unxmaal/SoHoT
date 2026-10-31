# Measure Specification

## Purpose
The measure tier: which screened rows are measured and in what order, how a paired run is planned, priced, launched in slices with interim looks, paused and resumed, which stored incumbent cells it may reuse, and the commands that replay or check what it did.

## Requirements

### Requirement: Which rows the measure step may take
The measure step SHALL plan a row only in the lane it is measured in (a repo row's own lane, else the scoped lane when the row's method serves it, else the row's filed lane) and only where its method runs; `measurable` SHALL apply that filter to the survivors before the `discover_top` limit, recording a cut when the limit drops any.

#### Scenario: A scoped survivor below the cut
- **WHEN** one image survivor sits behind several newer code survivors and the measure step is scoped to image with a limit smaller than the code rows
- **THEN** the image survivor is measurable, and unscoped the limit keeps that many rows
Test: tests/test_harness_cli_queue_scope.py::test_a_survivor_in_the_scoped_lane_below_the_cut_is_measured

#### Scenario: No method on a lane evals.run would skip
- **WHEN** every method is screened in every lane and the measure queue is planned, scoped or not, with the repo gate held or not
- **THEN** no method row is planned in a lane its method cannot run, some method is still planned where one applies, and a plain code model held by the gate is planned in the repo lane
Test: tests/test_method_lanes_1134.py::test_the_measure_planner_puts_no_method_on_a_lane_evals_run_would_skip

#### Scenario: A code-only method under the repo gate
- **WHEN** a method that runs only in the code lane is screened under code while the repo gate is held
- **THEN** it is planned in the code lane only, and a repo-scoped queue is empty
Test: tests/test_method_lanes_1134.py::test_a_plan_method_filed_under_code_is_not_scheduled_on_the_repo_lane

#### Scenario: A method row reaches measure on a lane it cannot run
- **WHEN** `_measure` is given a method row in a lane its method does not run
- **THEN** it plans nothing, prints that the method does not run that lane, and returns 0
Test: tests/test_method_lanes_1134.py::test_measure_refuses_a_method_row_on_a_lane_it_cannot_run

#### Scenario: The limit drops survivors
- **WHEN** more filtered survivors exist than the `discover_top` limit
- **THEN** the rows past the limit are dropped and a cut is recorded against `discover_top`
Test: untested

### Requirement: Live pauses resume first
The measure step SHALL find a pairing's live pause by lane and challenger alone (the newest row in state `paused`, whatever incumbent it ran against), and SHALL put every live pause, oldest first, ahead of new measurements, each pairing once.

#### Scenario: Paused measurements go first and once
- **WHEN** a pause is saved for a proposal and the fresh queue names that proposal and a new one
- **THEN** the paused proposal comes first and appears once
Test: tests/test_resume_813.py::test_paused_measurements_go_first_and_once

#### Scenario: A pause outside the scope
- **WHEN** a live pause names a proposal whose lane or method the scoped measure step does not take
- **THEN** it is not put at the head of the queue
Test: untested

### Requirement: Room for a queued measurement
`room_for` SHALL size one queued row by the memory headroom check the screen uses, pricing a method row by its weights, and SHALL report a row whose size is unknown as fitting, saying it proceeds unchecked.

#### Scenario: An unknown size
- **WHEN** a row's weights cannot be named
- **THEN** it fits, with no size, and says it proceeds unchecked
Test: untested

#### Scenario: An unbuildable spec
- **WHEN** the row's candidate spec cannot be built from the store
- **THEN** the row is sized by its weights alone
Test: untested

### Requirement: The challenger is released however the measure ends
`_measure_and_adopt` SHALL release every spec the measure loaded from the llama router and from the MLX server, on success, on a refusal and on an exception.

#### Scenario: The run raises
- **WHEN** the measure loaded a challenger and then raised
- **THEN** the exception propagates and that spec was released from both servers
Test: tests/test_router_unload.py::test_the_measure_unloads_its_challenger_however_it_ends

### Requirement: The pair runs in one invocation on one route
The measure step SHALL run incumbent and challenger in one evals.run invocation; when the challenger routes to a server other than the gateway it SHALL pass that `--gateway` and send the incumbent as the upstream model behind its alias, and SHALL keep the incumbent's alias when the run stays on the gateway. A row with no buildable candidate spec SHALL be an error.

#### Scenario: One invocation
- **WHEN** a tts challenger is measured
- **THEN** one argv names the lane and both candidates in one `--candidates`
Test: tests/test_harness_adopt.py::test_the_incumbent_and_challenger_run_in_one_paired_invocation

#### Scenario: A repo id routed off the gateway
- **WHEN** the challenger is a repo id the screen routes to another server
- **THEN** the paired argv carries that `--gateway`
Test: tests/test_harness_adopt_receipt.py::test_the_measure_routes_a_repo_id_the_way_the_screen_does

#### Scenario: The incumbent goes upstream with it
- **WHEN** the run is routed off the gateway and the incumbent is an alias with an upstream
- **THEN** `--candidates` names the upstream model, then the challenger
Test: tests/test_harness_adopt_receipt.py::test_the_incumbent_travels_as_a_repo_id_when_the_run_goes_upstream

#### Scenario: The run stays on the gateway
- **WHEN** the challenger is itself a gateway alias
- **THEN** the incumbent keeps its alias in `--candidates`
Test: tests/test_harness_adopt_receipt.py::test_the_incumbent_keeps_its_alias_when_the_run_stays_on_the_gateway

#### Scenario: No spec can be built
- **WHEN** no candidate spec can be built for the row in its lane
- **THEN** the measure returns 1 naming the row and runs nothing
Test: untested

### Requirement: The run directory is named and read back by name
The measure step SHALL name a fresh run's directory `<timestamp>-adopt-<lane>` under the runs root (or the held pause's directory on a resume) and SHALL read its receipt only from the store by that path; a results file on disk with no stored run SHALL read as none.

#### Scenario: The output directory
- **WHEN** a fresh paired run is launched
- **THEN** its argv carries `--out` ending in `-adopt-<lane>`
Test: tests/test_harness_adopt_receipt.py::test_the_measure_names_its_own_output_directory

#### Scenario: A stranger's run sorts higher
- **WHEN** another stored run's directory name sorts above this one
- **THEN** `_receipt_at` returns the run stored at the named path
Test: tests/test_harness_adopt_receipt.py::test_the_receipt_is_read_from_the_store_by_the_path_that_was_named

#### Scenario: Nothing stored at the path
- **WHEN** no run is stored at the named path
- **THEN** `_receipt_at` returns None, not another run
Test: tests/test_harness_adopt_receipt.py::test_a_path_with_no_stored_run_is_none_rather_than_someone_elses

#### Scenario: A results file on disk only
- **WHEN** the directory holds a results file but the store holds no run for it
- **THEN** `_receipt_at` returns None
Test: tests/test_harness_adopt_receipt.py::test_a_results_json_on_disk_is_not_a_stored_run

### Requirement: The receipt must describe the run asked for
After a finished run the measure step SHALL return 1 without a verdict when the eval exits non-zero (other than a pause, a deadline stop or a signal stop with checkpointed rows that is not an overrun stop), when no receipt is stored, when the receipt's summary names neither candidate, or when either candidate contributed no summary row; a run that exits 0 SHALL settle its held pause as done before its receipt is read.

#### Scenario: A receipt naming neither candidate
- **WHEN** the stored summary names two other candidates
- **THEN** the measure returns 1 saying the receipt does not describe the run just made
Test: tests/test_harness_adopt_receipt.py::test_a_receipt_naming_neither_candidate_is_refused

#### Scenario: One candidate contributed no rows
- **WHEN** the summary holds the challenger but not the incumbent, or the incumbent but not the challenger
- **THEN** the measure returns 1 naming the missing control or challenger and records nothing
Test: untested

#### Scenario: A working control still resolves
- **WHEN** the incumbent passed cases and the challenger ran and lost
- **THEN** the measure returns 0
Test: tests/test_harness_adopt_receipt.py::test_a_working_control_still_lets_a_loss_be_recorded

### Requirement: Refusals are matched on the receipt key
`_all_refused` SHALL return the failure class only when every row under the given receipt key carries a never-ran class, an empty string when any row reached a model or when there are no rows at all, and `NO_ROWS_FOR_CANDIDATE` when other candidates have rows and the key matches none.

#### Scenario: Every row refused
- **WHEN** every row for the candidate is a gateway refusal
- **THEN** a refusal class is returned
Test: tests/test_harness_adopt_receipt.py::test_rows_that_are_all_harness_refusals_are_named_as_such

#### Scenario: One row reached a model
- **WHEN** one row is a refusal and another failed on content
- **THEN** the result is empty
Test: tests/test_harness_adopt_receipt.py::test_one_row_that_reached_a_model_makes_it_the_candidates_result

#### Scenario: A real low score
- **WHEN** every row failed with no failure class
- **THEN** the result is empty
Test: tests/test_harness_adopt_receipt.py::test_a_real_low_score_is_not_a_refusal

#### Scenario: The wrong key
- **WHEN** rows exist only under an engine key and the bare repo id is asked
- **THEN** `NO_ROWS_FOR_CANDIDATE` is returned
Test: tests/test_harness_adopt_receipt.py::test_a_key_that_matches_no_row_is_reported_not_silently_ok

#### Scenario: The right key
- **WHEN** the engine key is asked
- **THEN** the refusal class is returned
Test: tests/test_harness_adopt_receipt.py::test_the_right_key_still_answers_the_real_question

#### Scenario: An empty receipt
- **WHEN** the rows are empty or None
- **THEN** the result is empty, not a key mismatch
Test: tests/test_harness_adopt_receipt.py::test_an_empty_receipt_is_not_a_key_mismatch

### Requirement: The plan's budget, side and spans
`_plan` SHALL take the lane's split and a power plan at the holdout's adjusted alpha, give the measurement a budget of `--power-budget-min` (default `power.BUDGET_MIN`) capped by the sweep's remaining ceiling, run the holdout alone and say dev was not run when dev and holdout together are projected over that budget, keep an explicit repeat, and SHALL record a plan longer than one budget as spanning several sweeps that pause and resume rather than refusing it.

#### Scenario: Dev does not fit
- **WHEN** dev and holdout are projected over the budget
- **THEN** the side is holdout, cases run is the holdout size, and dev_skipped says dev was not run
Test: tests/test_measure_budget.py::test_a_projection_over_budget_runs_the_holdout_only

#### Scenario: The argv names the holdout
- **WHEN** only the holdout fits
- **THEN** the paired argv carries `--split holdout` and the launch gets a positive deadline
Test: tests/test_measure_budget.py::test_the_measure_argv_names_the_holdout_when_dev_does_not_fit

#### Scenario: Longer than one budget
- **WHEN** the projection exceeds the budget
- **THEN** the plan names how many sweeps it is projected to span, paused and resumed, and has no refusal
Test: tests/test_over_budget_796.py::test_a_plan_projected_over_its_budget_is_sliced_across_sweeps_not_refused

#### Scenario: Inside one budget
- **WHEN** the projection fits the budget
- **THEN** the plan spans one sweep and says nothing of sweeps
Test: tests/test_over_budget_796.py::test_a_plan_inside_its_budget_spans_one_sweep

#### Scenario: An explicit repeat
- **WHEN** `--repeat` is given and the plan is over budget
- **THEN** that repeat is kept and the plan spans more than one sweep
Test: tests/test_over_budget_796.py::test_an_explicit_repeat_over_budget_keeps_its_repeat

#### Scenario: An unseen incumbent
- **WHEN** the incumbent has no stored draws
- **THEN** the plan is unmeasured and the printed line says what rate it assumes
Test: tests/test_incumbent_lookup.py::test_a_plan_that_falls_back_to_unseen_says_so_on_the_run

### Requirement: The pair is priced on this machine at the run's reply budget
`priced` SHALL return the incumbent's draws, the mean seconds per call, calls per case and the estimate for one paired run on this machine, at the reply budget the paired evals.run will derive for both specs (`_settings`); an incumbent receipt at another reply budget SHALL bound the seconds, and a method challenger SHALL be priced at its expected calls.

#### Scenario: This machine's median
- **WHEN** another machine has more incumbent rows at a different speed
- **THEN** the projection uses this machine's seconds
Test: tests/test_projection_696.py::test_the_incumbent_median_is_this_machines_not_the_one_with_most_rows

#### Scenario: A slower challenger
- **WHEN** the challenger's own screen rows are slower than the incumbent's
- **THEN** each is priced at its own seconds and the estimate records both as measured
Test: tests/test_projection_696.py::test_a_challenger_three_times_slower_is_priced_at_its_own_speed_and_the_inputs_are_kept

#### Scenario: A best-of challenger
- **WHEN** the challenger is a best-of method over a base that passes half its draws
- **THEN** it is projected at the base's expected calls, not its sample count
Test: tests/test_measure_budget.py::test_a_best_of_3_challenger_is_projected_at_its_bases_expected_calls

#### Scenario: A receipt at a smaller reply budget
- **WHEN** the incumbent's only receipt ran at a smaller reply budget
- **THEN** the incumbent is priced as bounded and the plan names that budget
Test: tests/test_over_budget_796.py::test_a_receipt_at_a_smaller_reply_budget_bounds_the_incumbent

#### Scenario: The reply budget follows the run's cap
- **WHEN** only the incumbent has a derived reply cap, and then a newcomer joins it
- **THEN** `_settings` gives the incumbent's cap alone and the lane budget with the newcomer, with an empty ladder
Test: tests/test_reply_cap_1352.py::test_evals_run_asks_at_the_cap_unless_told_otherwise

### Requirement: Nothing starts that cannot finish usefully
The measure step SHALL write a plan no run can decide as a verdict without launching evals.run unless it is resuming a held pause, and SHALL start no fresh launch once the sweep ceiling is reached, leaving the row for the next sweep.

#### Scenario: An undecidable plan
- **WHEN** the plan has no power even at the largest effect
- **THEN** no evals.run is launched and the measure returns 0
Test: tests/test_lane_too_small_1049.py::test_measure_does_not_run_a_plan_that_cannot_decide

#### Scenario: A held pause on an undecidable plan
- **WHEN** a pause is held for the pairing and the fresh plan is undecidable
- **THEN** the run is resumed rather than written as not run
Test: untested

### Requirement: The paired argv
`_argv` SHALL launch evals.run through the runner's launcher with the lane, repeat, `--out` and the pair as `--candidates`, adding `--split` when the side is not all, `--stop-at` at the slice's end, a `--plan-s` per candidate when both are priced, `--reuse` when stored cells are reused, `--resume` when a pause is held, and `--unscreened` on every repo-lane pairing once the measure step has judged the challenger's screen itself.

#### Scenario: A fresh slice
- **WHEN** a priced pair is launched with nothing held
- **THEN** the argv has `--stop-at`, a `--plan-s` for each candidate and no `--resume`
Test: tests/test_resume_813.py::test_a_run_paused_at_its_slice_is_recorded_with_progress_and_a_look

#### Scenario: The stop time
- **WHEN** a pair is launched with a one-minute budget
- **THEN** `--stop-at` falls within that minute of now
Test: tests/test_over_budget_796.py::test_an_over_budget_run_is_launched_to_pause_at_its_slice

#### Scenario: A repo pairing under --unscreened
- **WHEN** a repo pairing is measured with `--unscreened`
- **THEN** the measure step's screen guard is skipped and the paired argv carries `--unscreened`
Test: tests/test_repo_looks_1353.py::test_unscreened_skips_the_measure_steps_screen_guard

#### Scenario: Every repo pairing the guard lets run
- **WHEN** a repo pairing passes the measure step's screen guard without `--unscreened`, and a code pairing is measured
- **THEN** the repo argv carries `--unscreened` and the code argv does not
Test: tests/test_repo_looks_1353.py::test_every_repo_pairing_the_measure_step_lets_run_carries_unscreened_to_evals_run

#### Scenario: Reused cells
- **WHEN** the plan reuses stored incumbent cells
- **THEN** the reuse file is written in the run directory and the argv names it with `--reuse`
Test: untested

### Requirement: A repo pairing waits for the challenger's screen
`_screen_refusal` SHALL return the repo screen's refusal for a repo-lane challenger with no surviving repo screen, and SHALL return nothing for another lane, under `--unscreened`, or when a pause is held for the pairing; inside a sweep a refused row SHALL be reported on the sweep and return 0, and outside one it SHALL be an error.

#### Scenario: A held repo pause
- **WHEN** a live pause exists for the repo pairing and its directory is gone
- **THEN** no refusal is returned
Test: tests/test_repo_looks_1353.py::test_a_held_repo_pause_resumes_whatever_its_screen

#### Scenario: Refused inside a sweep
- **WHEN** a sweep measures an unscreened repo challenger
- **THEN** nothing runs, the sweep's lines say it was not measured, and the measure returns 0
Test: untested

### Requirement: Looks between slices of one launch
Inside its budget a paired run SHALL be launched in slices of `looks.LOOK_INTERVAL_S` (one slice when the budget is shorter); after a slice that stopped at its own stop time with budget left and new rows, the measure step SHALL take an interim look, keep the pause, and resume the same directory, stopping when the look decides and ending the launch with its pause kept when a slice adds no rows or the run paused for any other reason.

#### Scenario: The first slice
- **WHEN** a pair is launched with a budget longer than one look interval
- **THEN** its stop time is within one look interval of now
Test: tests/test_repo_looks_1353.py::test_a_paired_run_is_cut_into_look_slices_inside_its_budget

#### Scenario: A look decides for success
- **WHEN** the second slice gives every holdout case a cell with an overwhelming gain
- **THEN** that launch resumed the same directory, one verdict is recorded, and the pause is done with one continue look and one sweep, stopped for success
Test: tests/test_repo_looks_1353.py::test_a_decided_look_mid_run_stops_it_and_records_the_verdict

#### Scenario: A look decides for futility
- **WHEN** the second slice brings many lost cells
- **THEN** the verdict is not measured and names futility, and the pause is done
Test: tests/test_repo_looks_1353.py::test_a_hopeless_look_mid_run_stops_it_for_futility

#### Scenario: A slice adds nothing
- **WHEN** a slice ends with no new rows
- **THEN** the launch ends with no verdict and the pause kept, one sweep and two looks
Test: tests/test_repo_looks_1353.py::test_a_slice_that_ran_nothing_ends_the_run_with_its_pause_kept

#### Scenario: A budget under one interval
- **WHEN** the budget is half a look interval
- **THEN** the run is launched once
Test: tests/test_repo_looks_1353.py::test_a_budget_under_one_look_interval_is_one_slice

#### Scenario: A pause on request
- **WHEN** a slice pauses on request with budget left and new rows
- **THEN** it is not resumed inside the launch
Test: tests/test_repo_looks_1353.py::test_a_pause_on_request_is_never_resumed_inside_the_run

#### Scenario: A pause with no reason
- **WHEN** a slice pauses without saying why
- **THEN** it is not resumed inside the launch
Test: tests/test_repo_looks_1353.py::test_a_pause_with_no_reason_is_never_resumed_inside_the_run

### Requirement: Launching and stopping the eval group
`_launch` SHALL take the named lock (waiting behind its holder's declared deadline), record its own deadline on the heartbeat, and run the eval as its own process group, starting the deadline once the lock is held; past the deadline it SHALL stop the whole group, giving every member `STOP_GRACE_S` between TERM and KILL, and a TERM to the measure step, even one landing while the eval spawns, SHALL stop the eval's group before the measure exits with the TERM status.

#### Scenario: Past the deadline
- **WHEN** an eval whose grandchild holds the eval lock outlives its deadline
- **THEN** the launch reports timed out and the lock is free afterwards
Test: tests/test_measure_budget.py::test_a_run_past_its_deadline_is_stopped_and_the_lock_released

#### Scenario: Inside the deadline
- **WHEN** the eval exits in time
- **THEN** its exit code and stderr are returned and it is not timed out
Test: tests/test_measure_budget.py::test_a_run_inside_its_deadline_returns_its_output

#### Scenario: The deadline starts at the lock
- **WHEN** another process holds the lock longer than the run's deadline
- **THEN** the run is not timed out by its wait and exits 0
Test: tests/test_projection_696.py::test_the_deadline_starts_when_the_lock_is_taken_not_at_launch

#### Scenario: Waiting behind a holder
- **WHEN** the lock's holder declared a longer deadline
- **THEN** the heartbeat shows the holder's deadline and a waiting line while waiting, then this run's deadline with no waiting
Test: tests/test_liveness_705.py::test_measure_waits_behind_the_holders_deadline_and_declares_its_own

#### Scenario: The heartbeat deadline
- **WHEN** a run is launched with a deadline and no lock
- **THEN** the heartbeat records that deadline
Test: tests/test_liveness_705.py::test_measure_records_its_deadline_on_the_heartbeat

#### Scenario: The grace reaches grandchildren
- **WHEN** a group whose grandchild lingers on TERM is stopped
- **THEN** the leader is reaped, the grandchild saw TERM, and its lock is free
Test: tests/test_stop_group_677.py::test_measure_gives_the_grandchildren_the_grace_not_only_the_leader

#### Scenario: A TERM while the eval runs
- **WHEN** the measure step running an eval in its own session gets TERM
- **THEN** it exits with the TERM status and the eval is gone
Test: tests/test_launchd.py::test_a_terminated_measure_stops_the_eval_in_its_own_session

#### Scenario: A TERM inside the spawn
- **WHEN** TERM lands while the eval is being spawned
- **THEN** the measure step exits with the TERM status and the spawned eval has ended
Test: tests/test_launchd.py::test_a_term_that_lands_while_the_eval_spawns_still_stops_it

#### Scenario: A TERM while the spawn fails
- **WHEN** TERM lands and the spawn then raises
- **THEN** the measure step still exits with the TERM status
Test: tests/test_launchd.py::test_a_term_held_while_the_spawn_fails_is_still_a_term

### Requirement: Pause record
A paused paired run SHALL be kept as one `paused_runs` row per pairing holding its lane (trimmed, lower case), incumbent, challenger, proposal, run directory, resume identity, the plan it started with, cases done and total, sweeps spanned, every interim look taken so far, run id, machine and pause time; a later pause of the same run MUST update that row rather than add another, adding `spans` to its sweep count (none for a later look slice in the same sweep).

#### Scenario: The stored plan is kept for every resume
- **WHEN** a paused run's stored plan carries a stale challenger price and the run is resumed
- **THEN** the resume uses the same run directory and repeat the run started with
- **AND** the per-case plan seconds it is judged by are this sweep's, not the stored price
Test: tests/test_overrun_864.py::test_a_resumed_run_is_priced_afresh_and_keeps_its_exam

#### Scenario: A resumed plan takes this slice's budget
- **WHEN** a stored plan is resumed under a fresh plan
- **THEN** repeat, split side and per-cell odds come from the stored plan
- **AND** budget and deadline come from the fresh plan
Test: tests/test_resume_813.py::test_a_resumed_plan_keeps_its_exam_and_takes_this_slices_budget

### Requirement: Stale pause
A pause MUST be settled `stale` and its pairing restarted in a new run directory when the resume identity (lane, incumbent, split version, settings, knobs) differs from today's, when its checkpoint file is missing, or when evals.run refuses the resume as another exam (exit `watch.STALE`); the stale row's reason SHALL name what changed and where the paused rows stay.

#### Scenario: A changed split version
- **WHEN** a pause's stored identity carries another split version and the pairing is measured again
- **THEN** the old row is `stale` with a reason starting `stale: split_version changed since the pause at`
- **AND** the new launch has no `--resume`, a new run directory and a new `paused` row
Test: tests/test_resume_813.py::test_a_changed_holdout_version_makes_the_pause_stale_and_restarts

#### Scenario: The run's own checkpoint is another exam
- **WHEN** a resumed launch exits `watch.STALE`
- **THEN** the pause is settled `stale` and the pairing is launched once more without `--resume`
Test: tests/test_resume_813.py::test_a_run_whose_checkpoint_is_another_exam_restarts_fresh

#### Scenario: The checkpoint file is gone
- **WHEN** a live pause's run directory has no checkpoint file
- **THEN** the pause is settled `stale` naming its checkpoint and the pairing restarts fresh
Test: untested

### Requirement: Settled pause
A pause SHALL be settled `done` when its run finishes (before the receipt is read, so a run with nothing to conclude is never resumed again) and when an interim look stops the run for success or futility; a settled row MUST NOT be resumed.

#### Scenario: A finished resume with no receipt
- **WHEN** a paused run is resumed, finishes, and stores no receipt
- **THEN** the measure returns 1 and the pause row is `done`
Test: tests/test_resume_813.py::test_a_finished_resume_settles_its_pause_even_when_nothing_can_be_concluded

#### Scenario: A finished resume
- **WHEN** a paused run is resumed to the end and its receipt is read
- **THEN** the pause row is `done`, the verdict records the planned and observed seconds per paired case, and its power records the full `adopt.ALPHA`, because its look came before every case had a cell and tested no adopt
Test: tests/test_resume_813.py::test_a_finished_resume_spends_no_alpha_an_uncovered_look_did_not_test_and_stores_planned_and_observed_seconds

### Requirement: Stopped runs keep their rows
A paired run stopped by a signal (a negative exit, or a shell's exit for SIGTERM, SIGKILL or SIGINT) with checkpointed rows SHALL be kept as a pause (the measure returning `watch.PAUSED`) and resumed, unless its run directory's stop file names the watchdog's `overrun` criterion; a run that exits non-zero otherwise MUST be an error with no pause row. A run the watchdog stopped as an overrun SHALL end as a suspected harness defect: the measure returns 1, its held pause row is settled `defect`, the sweep is told, its rows stay on disk, and no later sweep resumes it, whether from a pause row or as an abandoned directory. A run directory a stopped run left with no pause row SHALL be resumed from its checkpoint when its name is the lane's adopt run, its checkpoint names this lane and exactly the incumbent and challenger, its progress state is running or paused, its directory is in no pause row of any state, neither its stop file nor the watchdog's recorded actions name an overrun stop of it, and its recorded process group is gone.

#### Scenario: A signal stop is a pause
- **WHEN** evals.run exits from a signal after checkpointing rows
- **THEN** the measure returns `watch.PAUSED` and a `paused` row holds the rows done
- **AND** the next measure resumes the same run directory
Test: tests/test_overrun_864.py::test_a_run_stopped_by_a_signal_is_kept_as_a_pause_and_resumed

#### Scenario: An overrun stop ends the run
- **WHEN** a resumed run is signalled after the watchdog named `overrun` in its stop file
- **THEN** the measure returns 1, the pause row is `defect` and says suspected harness defect, and the sweep's lines say so
- **AND** the next measure starts the pairing without `--resume`
Test: tests/test_overrun_864.py::test_a_run_the_watchdog_stopped_as_an_overrun_ends_flagged_and_is_not_resumed

#### Scenario: Any other watchdog stop is still a pause
- **WHEN** evals.run is signalled after the watchdog named another criterion, or no reason, in its stop file
- **THEN** the measure returns `watch.PAUSED` and the next measure resumes the same run directory
Test: tests/test_overrun_864.py::test_a_run_the_watchdog_stopped_for_another_reason_is_still_a_pause

#### Scenario: A held pause stopped as an overrun is not resumed
- **WHEN** a `paused` row's run directory names an overrun stop
- **THEN** the row is settled `defect` and the pairing starts without `--resume`
Test: tests/test_overrun_864.py::test_a_paused_run_whose_directory_names_an_overrun_stop_is_not_resumed

#### Scenario: An overrun stop made before stop files is read from the watchdog's record
- **WHEN** a `paused` row's run directory has no stop file, and the watchdog's actions record a stop of its command
- **THEN** it is not resumed only when that stop was an acted (not dry-run) overrun stop that signalled a group
Test: tests/test_overrun_864.py::test_an_overrun_stop_only_the_store_records_is_not_resumed

#### Scenario: An abandoned directory stopped as an overrun is left
- **WHEN** an otherwise abandoned run directory of this pairing names an overrun stop
- **THEN** it is not resumed
Test: tests/test_overrun_864.py::test_an_abandoned_directory_the_watchdog_stopped_as_an_overrun_is_left

#### Scenario: A crash is not a pause
- **WHEN** evals.run exits with a plain failure
- **THEN** the measure returns 1 and no pause row exists
Test: tests/test_overrun_864.py::test_a_crashed_run_is_still_an_error_not_a_pause

#### Scenario: An abandoned run directory is resumed
- **WHEN** a run directory for this pairing has a checkpoint, a running state, a dead process and no pause row
- **THEN** it is launched with `--resume` in that directory at the repeat and split its checkpoint names
- **AND** a `paused` row is saved for it
Test: tests/test_overrun_864.py::test_a_run_stopped_before_this_fix_is_found_by_its_checkpoint_and_resumed

#### Scenario: A directory that is not an abandoned run of this pairing
- **WHEN** the directory names another pairing, its process group is alive, a settled pause row names it, or its progress is done
- **THEN** it is left and the pairing starts fresh in a new directory
Test: tests/test_overrun_864.py::test_a_run_directory_that_is_not_an_abandoned_run_of_this_pairing_is_left

### Requirement: Alpha spending across looks
Each interim look SHALL spend alpha by the O'Brien-Fleming (Lan-DeMets) spending function at information fraction `t`, the paired holdout cells done over the holdout size times the plan's repeat (capped at one); a look MUST stop for success only when the adopt gate adopts at the alpha it may use, which is what is spent by `t` less what earlier looks spent.

#### Scenario: The spending curve
- **WHEN** alpha spent is read at fractions from zero to one
- **THEN** it is zero at the start, all of alpha at the end, and never falls
- **AND** at a quarter of the information almost none is spent
Test: tests/test_resume_813.py::test_spending_is_zero_at_the_start_all_of_alpha_at_the_end_and_never_falls

#### Scenario: An early lead does not stop for success
- **WHEN** a look at a fifth of the holdout sees a lead significant at full alpha
- **THEN** the look continues with no verdict and its spendable alpha is below full alpha
Test: tests/test_resume_813.py::test_an_early_lead_significant_at_alpha_does_not_stop_for_success

#### Scenario: Success at the spent alpha
- **WHEN** a look at half the holdout sees every paired cell gained
- **THEN** the look decides `success` with an adopting verdict
Test: tests/test_resume_813.py::test_an_overwhelming_lead_stops_for_success_with_the_spent_alpha

#### Scenario: A look with nothing new to spend
- **WHEN** a look's spendable alpha is zero because earlier looks spent all that is spent by its fraction
- **THEN** it does not stop for success, whatever the lead
Test: untested

### Requirement: Futility bound
A look SHALL stop a run for futility only when conditional power, under the plan's per-cell odds over the cells left (both shrunk by the plan's design effect), is below `FUTILITY_CP` and the challenger has gained no more cells than it lost; the futility verdict MUST NOT adopt and its reason SHALL start `futility:`, unless the plan's holdout could not power the lane's effect at any repeat (`adopt.lane_limit`), when it SHALL be the full gate's lane_too_small verdict, waiting on the lane's `cases:` until, with the futility reason inside it (#1452). With no cells left, or no discordant odds, conditional power SHALL be the final sign test's answer.

#### Scenario: Behind with no plausible path
- **WHEN** a look near the end of the holdout sees many cells lost and none gained
- **THEN** the look decides `futility` with conditional power below `FUTILITY_CP`
- **AND** the verdict does not adopt and its reason starts `futility:`
Test: tests/test_resume_813.py::test_a_challenger_behind_with_no_plausible_path_stops_for_futility

#### Scenario: A challenger ahead is never stopped
- **WHEN** a look sees more gained than lost with conditional power below `FUTILITY_CP`
- **THEN** the look continues
Test: tests/test_resume_813.py::test_a_challenger_ahead_is_never_stopped_for_futility

#### Scenario: A futility stop on a holdout no repeat could power
- **WHEN** a look stops for futility on a plan whose holdout needs more cases than it has
- **THEN** the verdict is lane_too_small with the until the full gate would give the same plan
Test: tests/test_futility_lane_too_small_1452.py::test_an_unpowered_futility_stop_is_lane_too_small_waiting_on_the_lanes_cases

#### Scenario: A powered futility stop is a loss
- **WHEN** a look stops for futility on a plan whose holdout reaches power at some repeat
- **THEN** the verdict is a candidate loss whose reason starts `futility:`
Test: tests/test_futility_lane_too_small_1452.py::test_a_powered_futility_stop_stays_a_loss

#### Scenario: Nothing left to run
- **WHEN** conditional power is asked with no cells remaining
- **THEN** it is one when the final sign test already adopts and zero when it does not
Test: tests/test_resume_813.py::test_conditional_power_with_nothing_left_is_the_final_answer

#### Scenario: Only the winning tail is summed
- **WHEN** conditional power is computed for any counts, cells left and odds
- **THEN** it equals the sum over every outcome the final sign test adopts on
Test: tests/test_weedout_1439.py::test_conditional_power_sums_only_the_winning_tail_of_each_count

### Requirement: Weed-out order
A paired measure and a confirmation run SHALL run their cases in the order `harness/weedout.py` declares before the run from the served incumbent's stored draws alone: expected discordant cells per incumbent second under the plan's effect, highest first, a case priced at no less than `MIN_S`, each repeat a pass over the order. The plan SHALL carry the order and the per-case rates behind it, so every look and resume reads the same ones. On an ordered run a look SHALL NOT test success, nor spend alpha, until every planned case has a cell from both candidates; its futility bound SHALL read the odds of the cells still to run, each case at its own rate. A confirmation run SHALL take a futility-only look every `looks.LOOK_INTERVAL_S` and record a keep when it stops.

#### Scenario: Informative and cheap cases first
- **WHEN** cases are ordered from their incumbent rates and seconds
- **THEN** expected discordant cells per second decides the order and an always-passed case goes last
Test: tests/test_weedout_1439.py::test_cases_go_by_expected_discordant_cells_per_second

#### Scenario: The run follows the order file
- **WHEN** evals.run is given `--order`
- **THEN** each repeat runs the named cases in that order and the unnamed after
Test: tests/test_weedout_1439.py::test_the_run_takes_cases_in_the_order_file_each_repeat_a_pass_and_unnamed_cases_last

#### Scenario: No adopt before full coverage
- **WHEN** an ordered run's look sees a lead that would succeed with cases still lacking a cell
- **THEN** it continues and spends no alpha
Test: tests/test_weedout_1439.py::test_an_ordered_run_never_adopts_before_every_case_has_a_cell_and_spends_no_alpha_there

#### Scenario: Futility on the cases left
- **WHEN** the cases left on an ordered run are ones the incumbent always passes and the challenger is not ahead
- **THEN** the look stops for futility where holdout-average odds would continue
Test: tests/test_weedout_1439.py::test_futility_reads_the_odds_of_the_cases_still_to_run_not_the_holdout_average

#### Scenario: A confirmation stops for futility
- **WHEN** a confirmation slice's look finds the challenger cannot reach the gate
- **THEN** a keep verdict is recorded and nothing adopts
Test: tests/test_weedout_1439.py::test_a_confirmation_slice_that_cannot_reach_the_gate_records_a_keep

### Requirement: Sweep ceiling
A discover sweep SHALL run under a wall-clock ceiling, `--ceiling-h` defaulting to `SWEEP_CEILING_H`; a measurement's slice MUST end at what is left of it (a deadline at most `DEADLINE_GRACE` past it plus one case), and no measurement SHALL start once nothing is left.

#### Scenario: The ceiling flag
- **WHEN** `soh discover --loop` is parsed with and without `--ceiling-h`
- **THEN** the ceiling is `SWEEP_CEILING_H` by default and the given hours otherwise
Test: tests/test_sweep_ceiling_806.py::test_the_ceiling_is_a_discover_flag_defaulting_to_the_knob

#### Scenario: A measurement past the ceiling
- **WHEN** a measurement projected to need more than the time left is planned inside a sweep
- **THEN** its budget is the time left and its deadline falls before its projection
Test: tests/test_sweep_ceiling_806.py::test_a_measurement_past_the_ceiling_gets_the_rest_of_it_as_its_slice

#### Scenario: Without a sweep
- **WHEN** a measurement is planned outside a sweep
- **THEN** its budget is `BUDGET_MIN`
Test: tests/test_sweep_ceiling_806.py::test_without_a_sweep_the_slice_is_the_measurement_budget

#### Scenario: The grace past the ceiling
- **WHEN** a measurement with a huge budget is planned inside a sweep
- **THEN** its deadline is the time left times `DEADLINE_GRACE` plus one case
Test: tests/test_sweep_ceiling_806.py::test_a_slice_never_runs_past_the_ceiling_by_more_than_its_grace

#### Scenario: Ceiling reached
- **WHEN** a measurement is asked for with no ceiling left
- **THEN** it returns 0 and nothing is launched
Test: tests/test_sweep_ceiling_806.py::test_nothing_is_started_once_the_ceiling_is_reached

### Requirement: What stops a sweep's measure step
A run paused on request SHALL halt the sweep (the measure step starts nothing more), except a memory pause, which SHALL only squeeze it so smaller measurements that fit still run; the measure step MUST start nothing more once the ceiling is reached, and SHALL say how many measurements wait for the next sweep.

#### Scenario: Paused on request halts
- **WHEN** a paired run pauses with a progress reason starting `paused on request`
- **THEN** the sweep's `halted` names the pause
Test: tests/test_resume_813.py::test_a_run_paused_on_request_halts_the_sweep

#### Scenario: A memory pause squeezes
- **WHEN** one run pauses for memory and another pauses on request for any other reason
- **THEN** the first sets only `squeezed` and the second only `halted`
Test: tests/test_memory_warn_1082.py::test_a_memory_pause_squeezes_the_sweep_and_any_other_request_halts_it

#### Scenario: Held back
- **WHEN** the sweep is halted, or its ceiling is reached
- **THEN** the loop starts nothing more and says `a run was paused on request` or `ceiling reached` with the count waiting
- **AND** with time left and no halt, or no sweep, it holds nothing back
Test: tests/test_resume_813.py::test_the_loop_starts_nothing_more_after_a_requested_pause_or_at_the_ceiling

### Requirement: Sweep summary and unused ceiling
At the end of a sweep the loop SHALL print a `=== sweep ceiling ===` block with the ceiling, its start, the time left and each line the measure step added; when more than `UNUSED_S` is left it SHALL name the unused time, the measurements waiting, and why (the measure step's stop reason, else that it ran out of measurements).

#### Scenario: The summary
- **WHEN** a sweep with an hour left finishes and the measure step added a line
- **THEN** the output has the ceiling block, the ceiling and the time left, and that line
Test: tests/test_sweep_ceiling_806.py::test_the_loop_summary_reports_the_ceiling_and_what_it_refused

#### Scenario: A sweep that ends early
- **WHEN** a sweep ends with more than `UNUSED_S` left after a pause on request
- **THEN** the unused report carries the time left, the count waiting and the stop reason, and the summary names it
- **AND** with less than `UNUSED_S` left there is no unused report
Test: tests/test_memory_warn_1082.py::test_a_sweep_that_ends_early_says_how_much_ceiling_it_left_and_why

### Requirement: Screen share of the ceiling
A sweep's screens SHALL be sized as `SCREEN_FRACTION` of the time left over the seconds one screen takes, measured as the mean gap from one screen verdict to the next screen verdict that ran a run within `SCREEN_DAYS`, ignoring gaps longer than the ceiling, and `SCREEN_S` when the store has none; an explicit `--top` MUST set the count instead.

#### Scenario: Seconds per screen
- **WHEN** screen verdicts span two nights, one without a run
- **THEN** the seconds per screen is the mean of the gaps ending at a verdict with a run, leaving out the gap across nights
Test: tests/test_lane_heads_1084.py::test_seconds_per_screen_is_the_mean_gap_between_screens_in_one_sweep

#### Scenario: No stored screens
- **WHEN** the store holds no screen verdicts
- **THEN** the seconds per screen is `SCREEN_S`
Test: tests/test_lane_heads_1084.py::test_seconds_per_screen_falls_back_when_the_store_has_none

#### Scenario: Screens that fit
- **WHEN** the loop sizes a full sweep with no `--top`, and again with one
- **THEN** the count is the screen share of the ceiling over the seconds per screen, and the given top otherwise
Test: tests/test_lane_heads_1084.py::test_screens_that_fit_take_the_screen_share_of_what_is_left

### Requirement: Stored incumbent cells join the run's rows
When the plan reuses stored incumbent draws, the measure step SHALL lower the projection by the incumbent's share of the per-cell cost, and when reading a paused or finished run SHALL add the stored cells the run actually accepted, rescored at the incumbent's yield stop point from the run's receipt, to the run's rows and summary, carrying the reuse evidence on the verdict; an incumbent identity that cannot be read SHALL mean no reuse, said on the run.

#### Scenario: The stop point
- **WHEN** a run's receipt names a yield stop point for the incumbent's key
- **THEN** `_stopped_at` returns those tokens, and None for another key or a missing run
Test: tests/test_yield_stop_1127.py::test_reused_draws_are_rescored_at_the_runs_stop_point

#### Scenario: An unreadable identity
- **WHEN** the incumbent's content identity has no digest
- **THEN** the plan reuses nothing and the printed line names what was unreadable
Test: untested

#### Scenario: The projection without reused cells
- **WHEN** some incumbent cells are reused
- **THEN** the projected seconds fall by the incumbent's share of the reused fraction
Test: untested

### Requirement: Recording from the measure step
The measure step SHALL record each verdict with the run's planned and observed seconds per paired case (the candidates' per-case seconds summed, or none when one is unknown), on the proposal the candidate maps to so it leaves the survivors, and SHALL print and skip a verdict the store refuses as an illegal transition rather than fail the sweep.

#### Scenario: The proposal leaves the survivors
- **WHEN** a screened proposal is measured under a spec of another name
- **THEN** no survivor remains
Test: tests/test_harness_adopt_receipt.py::test_a_measured_proposal_leaves_the_survivors_list

#### Scenario: A refused transition
- **WHEN** recording raises an illegal transition
- **THEN** the measure prints that it skipped the proposal and returns 0
Test: tests/test_store_state.py::test_a_refused_adoption_returns_to_the_measure_loop

### Requirement: A never-passing typed incumbent gives way before the sweep
Before measuring, the sweep SHALL let each typed lane whose served incumbent is zero-pass take its incumbent from measurement (`take_incumbents`); the measure step SHALL try the same take before a pairing, measure against the taken incumbent when one is adopted, and otherwise run the pair as a screen whose verdict keeps the incumbent, trying the take again afterwards. `take_measured` with `dry_run` SHALL record nothing.

#### Scenario: A dry run
- **WHEN** `take_measured` runs with `dry_run` on a winning candidate
- **THEN** it prints that it would adopt and records nothing
Test: untested

### Requirement: Zero-pass incumbent
A lane with no adoption here whose typed incumbent passed none of at least `MIN_CASES` (knob `zero_pass_min_cases`) distinct stored cases SHALL count as zero-pass; a paired run against a zero-pass incumbent MUST be a screen that adopts nothing, recorded as declined with a reason starting `screen only`.

#### Scenario: Enough cases, no pass
- **WHEN** the typed incumbent has failed `MIN_CASES` distinct stored cases and passed none
- **THEN** it is zero-pass with its case and draw counts
Test: tests/test_incumbent_from_measurement_1110.py::test_a_typed_incumbent_that_passed_none_of_enough_stored_cases_is_zero_pass

#### Scenario: Too few cases or one pass
- **WHEN** it has one case fewer than `MIN_CASES`, or one stored pass
- **THEN** it is not zero-pass
Test: tests/test_incumbent_from_measurement_1110.py::test_too_few_stored_cases_or_one_pass_is_not_zero_pass

#### Scenario: A paired run is a screen
- **WHEN** a repo challenger is measured paired against a zero-pass incumbent
- **THEN** the lane adopts nothing and the verdict is declined, starting `repo: screen only`
Test: tests/test_incumbent_from_measurement_1110.py::test_a_paired_run_against_a_zero_pass_incumbent_is_a_screen_and_adopts_nothing

#### Scenario: A lane with an adoption
- **WHEN** the lane already has an adoption here
- **THEN** its typed incumbent is never zero-pass
Test: untested

### Requirement: Incumbent taken from measurement
For a zero-pass lane the best local candidate (by the lane's ranking) with a patch-harness row on every case of the current exam under its cases digest on this machine SHALL be decided by the adopt gate against a never-passing baseline (failed, the lane's metric at zero, on every case), counting each other measured candidate as a comparison; the verdict reason SHALL start `taken from measurement`. No candidate with every case MUST mean no verdict.

#### Scenario: One gained case
- **WHEN** the best measured candidate passed one case of the exam
- **THEN** it is not adopted and the reason names one gained case
Test: tests/test_incumbent_from_measurement_1110.py::test_one_gained_case_over_a_zero_pass_incumbent_is_not_adopted

#### Scenario: Enough gained cases
- **WHEN** the best measured candidate passed enough cases of the exam
- **THEN** it is adopted, the reason starts `taken from measurement` and the evidence names the exam digest
Test: tests/test_incumbent_from_measurement_1110.py::test_enough_gained_cases_take_the_incumbent_from_measurement

#### Scenario: A cut reply is no loss
- **WHEN** many of the candidate's replies were cut at the reply budget
- **THEN** it is still adopted with no case lost
Test: tests/test_incumbent_from_measurement_1110.py::test_a_cut_reply_is_no_loss_against_the_zero_pass_incumbent

#### Scenario: Only the whole current exam
- **WHEN** the candidate's runs miss one exam case or carry another digest
- **THEN** there is no verdict
Test: tests/test_incumbent_from_measurement_1110.py::test_only_a_run_of_every_case_of_the_current_exam_counts

#### Scenario: The morning report names the source
- **WHEN** a zero-pass lane is read before and after the incumbent is taken from measurement
- **THEN** before, it is the typed default that passed none and the next sweep takes the candidate; after, it is the adopted measured spec with the `taken from measurement` detail
Test: tests/test_incumbent_from_measurement_1110.py::test_soh_morning_names_the_repo_incumbent_and_its_source

### Requirement: Whole current exam
A stored run SHALL count as a candidate sitting the current exam only when its cases digest equals the one its lane, split and repeat give now, its harness is the patch harness, and the candidate has a row on every case of it; measured candidates on that exam SHALL be ranked by the lane's one ordering rule, environment errors included.

#### Scenario: The exam a run records
- **WHEN** a run is recorded and the exam is recomputed for its split and repeat
- **THEN** the digests match and the candidate sat the exam
- **AND** against a suite with one case fewer it did not
Test: tests/test_exam_ranking_1120.py::test_the_exam_a_run_records_is_the_one_baseline_recomputes

#### Scenario: A repair harness run
- **WHEN** a run on the exam's digest was made under the repair harness
- **THEN** it did not sit the exam
Test: tests/test_repo_repair_890.py::test_winners_never_rank_a_repair_run_on_the_exam

#### Scenario: Environment errors in the ranking
- **WHEN** two candidates measured on the same exam differ in environment errors
- **THEN** the measured order is the adopt ranking's, which sees those errors
Test: tests/test_env_error_coverage_1116.py::test_adoption_and_measured_baselines_see_the_environment_errors

### Requirement: Engine clock from measurement
An engine runner's clock per case SHALL be `MARGIN` times the slowest generated case stored for that engine (the candidate's prefix before the first slash) in that lane on this machine, rounded up and never under `FLOOR_S`, once `MIN_CASES` such cases exist, and the engine's own ceiling otherwise; a case that timed out, failed to load or crashed MUST NOT count. Each run SHALL record every engine runner's clock and its basis on the receipt as provenance, not a comparison axis.

#### Scenario: Enough finished cases
- **WHEN** another model of the same engine has `MIN_CASES` generated cases in the lane here
- **THEN** the clock is `MARGIN` times the slowest of them, from `measured`
Test: tests/test_engine_timeout_708.py::test_an_engine_with_enough_finished_cases_runs_at_the_margin_times_its_slowest

#### Scenario: Too few here
- **WHEN** the engine has too few cases in this lane on this machine, however many it has in another lane or on another machine
- **THEN** the clock is its ceiling, from `ceiling`
Test: tests/test_engine_timeout_708.py::test_an_engine_with_too_few_finished_cases_keeps_its_own_ceiling

#### Scenario: A timed-out case
- **WHEN** a case cut by the clock is stored with the timeout class
- **THEN** it does not raise the clock
Test: tests/test_engine_timeout_708.py::test_a_timed_out_case_does_not_raise_the_clock_it_was_cut_by

#### Scenario: Load failures and crashes
- **WHEN** the only stored cases failed to load or crashed
- **THEN** the clock is the ceiling
- **AND** content failures and passes do count toward the basis
Test: tests/test_engine_timeout_1256.py::test_load_failures_do_not_count_toward_the_engine_basis

#### Scenario: The floor
- **WHEN** an engine's slowest case is a fraction of a second
- **THEN** the clock is `FLOOR_S`, and a margin of zero keeps the ceiling
Test: tests/test_engine_timeout_708.py::test_the_derived_timeout_never_goes_below_the_floor

#### Scenario: The margin is an exam knob
- **WHEN** a run rebinds `engine_timeout`
- **THEN** the derived clock uses that margin, and the lane's knob settings carry it
Test: tests/test_engine_timeout_708.py::test_the_margin_is_an_exam_knob_a_run_can_set

#### Scenario: The receipt records each clock
- **WHEN** an eval run sets clocks on a process runner and a chain runner
- **THEN** each runner's timeout and basis is on the receipt and survives a round trip
- **AND** two receipts differing only in it are comparable
Test: tests/test_engine_timeout_708.py::test_an_eval_run_records_each_engine_runner_timeout_and_its_basis_on_the_receipt

#### Scenario: The backtest
- **WHEN** `backtest` reads an engine's stored cases
- **THEN** per lane, engine and machine it counts the cases each margin would have cut had its clock been set from the cases before them
Test: tests/test_engine_timeout_708.py::test_the_backtest_counts_the_cases_a_margin_would_have_cut

### Requirement: Rerun at the ceiling
A case cut under a derived clock below the engine's ceiling SHALL be rerun once at the ceiling, at most `RERUNS` times per runner per run, and when the rerun finishes the runner's clock SHALL become `MARGIN` times the rerun's time (not below the cut clock, not above the ceiling); a rerun that times out, a clock already at the ceiling, or a clock the caller chose MUST cut as before. A screen's deadline SHALL allow the case count at the clock plus `RERUNS` cases at the ceiling.

#### Scenario: A correct but slower candidate
- **WHEN** a candidate several times slower than its engine's history is cut under the derived clock
- **THEN** it is rerun at the ceiling and graded as a pass, the wait recorded, and the clock raised to the margin times its time
- **AND** its next case runs at the new clock with no rerun
Test: tests/test_engine_timeout_1256.py::test_a_correct_candidate_five_times_slower_than_the_engine_history_is_graded_not_cut

#### Scenario: A wedged candidate
- **WHEN** the rerun at the ceiling also times out
- **THEN** the case is a timeout naming the ceiling, the clock stays the derived one, and later cases are cut without another rerun
Test: tests/test_engine_timeout_1256.py::test_a_wedged_candidate_is_still_cut

#### Scenario: No reruns
- **WHEN** `engine_timeout_reruns` is zero
- **THEN** a slow case is cut at the derived clock with no rerun
Test: tests/test_engine_timeout_1256.py::test_reruns_zero_keeps_the_derived_clock_cut

#### Scenario: A clock at the ceiling
- **WHEN** a derived runner's clock is its ceiling and a case passes it
- **THEN** the case is a timeout and nothing is rerun
Test: tests/test_engine_timeout_1256.py::test_a_case_at_the_ceiling_is_not_rerun

#### Scenario: A caller's clock
- **WHEN** the caller set the runner's timeout itself
- **THEN** a case past it is a timeout and nothing is rerun
Test: tests/test_engine_timeout_1256.py::test_a_clock_a_caller_chose_is_not_rerun

#### Scenario: The screen deadline
- **WHEN** an engine has a derived clock
- **THEN** a screen's deadline is the screen cases at that clock plus `RERUNS` cases at the ceiling, and just the cases at the clock when reruns are zero
Test: tests/test_engine_timeout_1256.py::test_the_screen_deadline_allows_the_rerun_at_the_ceiling

### Requirement: Stored paired comparisons
The measure gain SHALL read as evidence every stored measure run that a proposal's adopt verdict or a paused run names, recomputing gained, lost and unchanged cells from the run's own result rows, and SHALL count a comparison only when both the link's time and the run's recorded time fall before the cutoff it is asked for.

#### Scenario: Evidence after the replayed night is not read
- **WHEN** a paired comparison was decided after the cutoff a replay asks for
- **THEN** it is not among the comparisons as of that cutoff
- **AND** a row that ranked first on that evidence today ranks behind an unmeasured row of equal cost as of the cutoff
Test: tests/test_measure_gain_1315.py::test_evidence_after_the_replayed_night_is_not_read

#### Scenario: Both the run and its verdict must precede the cutoff
- **WHEN** one comparison's run is recorded before the cutoff but its verdict after, and another's verdict is before but its run is recorded after
- **THEN** neither is read as of the cutoff
- **AND** both are read with no cutoff
Test: tests/test_measure_gain_1315.py::test_a_comparison_counts_only_once_both_its_run_and_its_verdict_precede_the_night

#### Scenario: A run that is not one challenger against one incumbent
- **WHEN** a linked run holds other than two receipt keys, or no single key whose candidate belongs to the named proposal
- **THEN** it yields no comparison
Test: untested

#### Scenario: A paused run counts as a comparison
- **WHEN** a paused run names a proposal and its run id
- **THEN** the run's cells so far are read as that proposal's comparison as of the pause time
Test: untested

#### Scenario: A store without the tables
- **WHEN** the store cannot answer the comparison query (a stub, a missing table, an older schema)
- **THEN** there are no comparisons and scoring goes on without them
Test: untested

### Requirement: Which comparisons bear on a row
A comparison SHALL bear on a queue row only in the row's own lane: in full when it is the row's own proposal, and shrunk as a relative when it is a crossing of the same method head (for a crossing row) or a model of the same lineage family (for a model row); a relative's cells SHALL count as n times `RELATED_CELLS` over n plus `RELATED_CELLS`, with its net gain scaled the same way.

#### Scenario: Own cells in full, a relative's shrunk, another lane's not at all
- **WHEN** a crossing row has its own paired run and another base model under the same method head has one, in the same lane
- **THEN** its own evidence carries every cell and its full net gain
- **AND** the relative's carries the shrunk cell count and the net gain scaled by the same factor
- **AND** in another lane neither comparison is evidence
Test: tests/test_measure_gain_1315.py::test_own_paired_cells_count_in_full_and_a_relatives_are_shrunk

#### Scenario: A crossing with positive evidence of its method head
- **WHEN** a crossing whose method head gained on another base model and an unmeasured model of equal cost are queued
- **THEN** the crossing ranks first, its evidence source is a method run with the shrunk cell count
- **AND** the model reads no evidence from the crossing's comparison
Test: tests/test_measure_gain_1315.py::test_a_crossing_with_stored_positive_evidence_outranks_an_unmeasured_model_of_equal_cost

#### Scenario: A family whose members lost
- **WHEN** members of a lineage family lost their paired runs and an unmeasured member of it competes with an unmeasured model of another family at equal cost
- **THEN** the other family's model ranks first
- **AND** the member's evidence is the family's runs
Test: tests/test_measure_gain_1315.py::test_a_family_whose_members_lost_ranks_below_an_unmeasured_family_of_equal_cost

### Requirement: Screen evidence
A row's screen rows in its lane, recorded before the cutoff, SHALL count as evidence at full weight: each case's draw minus the served incumbent's stored pass rate on the same base case, over the cases they share.

#### Scenario: A screen above the incumbent's rates
- **WHEN** one model's screen passed every case and another's passed none, on cases the incumbent passes at a known rate
- **THEN** the first model's posterior mean is above zero and the second's below
- **AND** the first's mean is the prior weighted by `PRIOR_CELLS` plus the screen's net gain, over `PRIOR_CELLS` plus the shared cases
Test: tests/test_measure_gain_1315.py::test_a_screen_that_beats_the_incumbents_rates_lifts_the_mean

#### Scenario: A screen recorded after the cutoff
- **WHEN** a screen ran after the cutoff a replay asks for
- **THEN** none of its rows are read as of that cutoff, and all of them are read with no cutoff
Test: tests/test_measure_gain_1315.py::test_evidence_after_the_replayed_night_is_not_read

#### Scenario: No case in common with the incumbent
- **WHEN** none of a screen's base cases has a stored incumbent rate
- **THEN** the screen adds no evidence
Test: untested

### Requirement: Posterior and expected gain
The gain SHALL be a normal posterior on the per-cell net gain over the incumbent, with prior mean `PRIOR_MEAN` worth `PRIOR_CELLS` cells and prior sd `PRIOR_SD` shrinking with the evidence's cells, and the expected gain SHALL be the expected improvement above the lane's adopt effect, so a gain the gate cannot adopt is worth nothing.

#### Scenario: Only what clears the lane's effect counts
- **WHEN** the posterior is near certain at or below the effect, or near certain above it
- **THEN** the expected gain is zero in the first case and the excess over the effect in the second
- **AND** at equal mean a wider sd is worth more, and at equal sd a higher mean is worth more
Test: tests/test_measure_gain_1315.py::test_expected_gain_counts_only_what_clears_the_lanes_effect

#### Scenario: No evidence
- **WHEN** a row has no comparison and no screen evidence
- **THEN** its mean is `PRIOR_MEAN` and its sd is `PRIOR_SD`
Test: untested

### Requirement: Price in GPU-minutes
A row's price SHALL be its lane's holdout cases times the measure step's priced seconds per call times its calls, in minutes, priced once per name and lane per queue; a row SHALL be unpriced, with the reason recorded, when the lane has no holdout cases, no incumbent, the row has no candidate spec, no seconds per call are stored or estimated, or pricing raises.

#### Scenario: A lane with no holdout cases
- **WHEN** the row's lane has no holdout cases
- **THEN** the row is unpriced and the reason names the lane
Test: untested

#### Scenario: A lane with no incumbent or a row with no spec
- **WHEN** the lane has no incumbent, or the row's name spells no candidate for the lane
- **THEN** the row is unpriced and the reason says which
Test: untested

#### Scenario: Pricing raises
- **WHEN** reading the price raises a store, value or OS error
- **THEN** the row is unpriced with a reason that starts `pricing failed:` and the queue is still ordered
Test: untested

### Requirement: Queue order by gain per GPU-minute
The measure queue SHALL be ordered by expected gain per GPU-minute, highest first, every priced row ahead of every unpriced row, and rows of equal key, and unpriced rows among themselves, SHALL keep the order they arrived in.

#### Scenario: A cheaper crossing with equal evidence
- **WHEN** two crossings have equal stored evidence and one is cheaper
- **THEN** the cheaper one is first
- **AND** when the price flips, the order flips
Test: tests/test_measure_gain_1315.py::test_a_cheaper_crossing_with_equal_evidence_measures_first

#### Scenario: Unpriced rows after the priced ones
- **WHEN** priced and unpriced rows are queued together
- **THEN** the priced rows come first by key and the unpriced follow in their arrival order with no key
- **AND** an unpriced row's line says `unpriced` with its reason
Test: tests/test_measure_gain_1315.py::test_an_unpriced_row_keeps_its_place_after_the_priced_ones

#### Scenario: Equal keys keep the survivors order
- **WHEN** rows have equal keys
- **THEN** they keep the order they arrived in, whichever order that is
Test: tests/test_measure_gain_1315.py::test_equal_keys_keep_the_survivors_order

#### Scenario: A priced row with no gain
- **WHEN** a priced row's expected gain is zero
- **THEN** it still goes before an unpriced row
Test: tests/test_measure_gain_1315.py::test_a_priced_row_with_no_gain_still_goes_before_an_unpriced_one

### Requirement: A gated row is keyed as a chain
When the repo gate holds a row, its score SHALL carry the repo-lane comparison that must run first, and its key SHALL be the better of that comparison's own gain per minute and the pair's summed gain over its summed minutes; an unpriced first comparison SHALL leave the pair unpriced, and an unpriced row behind a priced first comparison SHALL take the first comparison's key.

#### Scenario: The pair is priced with the minutes it waits on
- **WHEN** a code row the gate holds is scored as gated
- **THEN** its key is the maximum of the repo comparison's key and the pair's summed gain over summed minutes
- **AND** that key is below the row's key scored alone
Test: tests/test_repo_share_1323.py::test_a_gated_code_rows_repo_comparison_runs_right_before_it_keyed_as_the_pair

#### Scenario: An unpriced repo comparison
- **WHEN** the repo comparison a gated row waits on is unpriced
- **THEN** the pair has no key and sorts with the unpriced rows
Test: untested

#### Scenario: An unpriced row behind a priced repo comparison
- **WHEN** a gated row is unpriced but its repo comparison is priced
- **THEN** the pair's key is the repo comparison's key
Test: untested

### Requirement: Each row's key is said
The measure step SHALL say, before it starts, one numbered line per queued row in queue order naming the row, its lane, its expected gain per cell above the effect, its mean and sd, its minutes or its unpriced reason, its key per hour, and its evidence sources or that it has none; a gated row's line SHALL also say it comes after its repo comparison.

#### Scenario: The sweep says the keys
- **WHEN** the measure step orders a crossing with method evidence and an unmeasured model
- **THEN** the crossing is first and its said line starts `gain:`, numbers it first, and gives its name and lane, a key per hour, and its method run as evidence
Test: tests/test_measure_gain_1315.py::test_the_measure_step_says_each_rows_key

#### Scenario: A gated row's line
- **WHEN** the queue holds a gated code row
- **THEN** its line says it comes after its repo comparison
Test: tests/test_repo_share_1323.py::test_a_gated_code_rows_repo_comparison_runs_right_before_it_keyed_as_the_pair

### Requirement: A night's queue rebuilt as of that night
The replay SHALL rebuild each night's queue from the store as it stood when that night's measuring began: the proposals whose newest verdict before then is a passed screen, newest first; the pauses begun before then and neither stale nor decided since, oldest first; and, on a night that measured in the repo lane, the repo winners owed their code comparison then.

#### Scenario: Survivors as they stood that night
- **WHEN** one proposal screened, then lost at adopt, and another screened later
- **THEN** as of a time between the screen and the loss the first is the only survivor, and as of now the second is
- **AND** as of now the replay's survivors are the store's survivors
Test: tests/test_measure_gain_1315.py::test_the_replay_reads_survivors_as_they_stood_that_night

#### Scenario: A measurement's start from its out dir
- **WHEN** a path carries a measure step's out dir stamp followed by `-adopt-`
- **THEN** the start time is read from that stamp
- **AND** a path no measure step wrote has no start
Test: tests/test_measure_gain_1315.py::test_a_measurement_start_is_read_from_its_out_dir

#### Scenario: Pauses held that night
- **WHEN** a proposal's newest pause began before the night's measuring, is not stale, and no adopt verdict for it fell between its start and that time
- **THEN** it is held for that night, oldest pause first
Test: untested

#### Scenario: What a night measured
- **WHEN** a measurement started fresh inside the night's window, or a resumed slice paused or was decided inside it
- **THEN** the fresh start is placed at its out dir time, and a resume at its pause or verdict time less one `BUDGET_MIN` slice but not before the night's start
Test: untested

#### Scenario: Owed only from a repo win before that time
- **WHEN** a proposal's repo-lane win was decided after the replayed time
- **THEN** it is not owed its code comparison as of that time, and it is owed as of now
- **AND** with no cutoff the replay owes exactly the rows the gate owes
Test: tests/test_repo_share_1323.py::test_the_replay_owes_a_code_comparison_only_from_its_repo_win

### Requirement: Both orders walked against the night's window
For each night the replay SHALL walk the survivors order and the gain order, each through the family order, the diversity slot (memory unchecked), the held pauses and the repo gate, against the window from the first measurement to the sweep ceiling `SWEEP_CEILING_H`, every row priced at today's seconds per call with only its evidence read as of that night; each row SHALL take the least of its minutes, one `BUDGET_MIN` slice, and what is left, an unpriced or zero-minute row one slice, and a row reached with nothing left SHALL be cut.

#### Scenario: The walk cuts what the window has no time for
- **WHEN** rows are walked against a window shorter than their summed time
- **THEN** a row longer than a slice takes one slice, an unpriced row takes a slice or what is left, and the row reached at zero is cut
Test: tests/test_measure_gain_1315.py::test_the_walk_cuts_what_the_window_leaves_no_time_for

#### Scenario: A row priced at zero minutes
- **WHEN** a row priced at zero minutes and an unpriced row are walked against a long window
- **THEN** each takes one slice, and the zero-minute row has no key and reads as unpriced
Test: tests/test_measure_gain_1315.py::test_a_row_priced_at_zero_minutes_is_charged_a_slice_like_an_unpriced_one

#### Scenario: A row the gate holds that night is left out
- **WHEN** the gate is on for a replayed night and a code row has not won its repo comparison
- **THEN** its repo comparison is queued and the code row itself is left out
Test: tests/test_repo_share_1323.py::test_the_replay_leaves_out_a_row_the_gate_holds_that_night

#### Scenario: A night with no measurement
- **WHEN** nothing was measured in a replayed night
- **THEN** its measuring is taken to start at the sweep start plus the ceiling times `SCREEN_FRACTION`
Test: untested

#### Scenario: Which nights are replayed
- **WHEN** a replay of a number of days is asked
- **THEN** the nights are the most recent evenings at the first discovery hour whose ceiling has passed, oldest first
- **AND** the repo gate is on for a night only when that night measured in the repo lane
Test: untested

### Requirement: Replay and queue reports
The replay report SHALL say, per night, when measuring began, the minutes to the ceiling, the survivors and pauses it faced, what it measured, and for each order the rows it takes, the minutes each lane takes, and how many rows it cuts, naming at most `--head` rows of each (every row at a head of zero); today's report SHALL list today's survivors by gain per GPU-minute, numbered, one line per row.

#### Scenario: The head of a replayed night
- **WHEN** a replayed night's orders take and cut more rows than the head, at a head of zero and at a head of two
- **THEN** at zero every taken and cut row is named, and at two each line names two
Test: tests/test_measure_gain_1315.py::test_the_replay_lists_every_row_at_head_0_and_head_rows_otherwise

#### Scenario: Minutes each lane takes
- **WHEN** a replayed night's orders take rows from several lanes
- **THEN** each order has a `minutes:` line with each lane's minutes, most first
Test: tests/test_repo_share_1323.py::test_the_replay_says_the_minutes_each_lane_takes

#### Scenario: Today's queue
- **WHEN** today's queue is asked with a head of zero
- **THEN** every survivor the lane filter takes is listed by key, numbered from one
Test: untested

### Requirement: The measure-order command is read-only
`soh measure-order` SHALL open the store read-only, or a copy named by `--store` opened immutable, lend that one connection to every reader it reaches (pricing, routing, reply caps) so no other store is opened, print today's queue or, with `--replay`, the per-night replay, emit the same lines as one object under `--json`, and exit with code 0.

#### Scenario: A store copy
- **WHEN** `--store` names a copy and today's queue and a replay are printed from it
- **THEN** the survivor in the copy is listed and the store is never opened through `connect`
Test: tests/test_measure_gain_1315.py::test_measure_order_reads_only_the_store_it_is_given

#### Scenario: Replay or today
- **WHEN** `--replay` is given a number of days
- **THEN** the replay report is printed; without it today's queue is printed, limited to `--head` rows
Test: untested

### Requirement: Incumbent cells planned from stored draws
A paired measure SHALL take an incumbent cell from the store instead of running it when at least `MIN_DRAWS` stored draws of that base case and repeat index exist from runs whose recorded identity digest is the incumbent's now and whose recorded per-case digest for that case is today's, taking the newest; a draw that never ran SHALL not count, and an empty digest SHALL reuse nothing.

#### Scenario: Stored draws under the same digest
- **WHEN** an incumbent-only run is stored and a paired run is planned under the same identity
- **THEN** every incumbent cell is reused and none is fresh
- **AND** the paired run sends no incumbent calls and records the reuse and the identity
Test: tests/test_incumbent_reuse_1094.py::test_stored_draws_under_the_same_digest_send_no_incumbent_calls

#### Scenario: A case without a matching draw
- **WHEN** one case's stored row is gone
- **THEN** that one cell runs fresh and every other is reused
Test: tests/test_incumbent_reuse_1094.py::test_a_case_without_a_matching_draw_runs_fresh

#### Scenario: A changed binary, model, sampling or harness prompt
- **WHEN** the runtime binary, the model file, the sampling, or the prompt the harness sends changes after the stored run
- **THEN** no cell is reused
- **AND** a reuse plan written before the change is refused by the run, which runs every incumbent cell
Test: tests/test_incumbent_reuse_1094.py::test_the_same_rows_under_a_changed_binary_model_or_sampling_run_fresh

#### Scenario: Fewer draws than required
- **WHEN** a cell has fewer matching draws than `MIN_DRAWS`
- **THEN** it runs fresh
Test: untested

### Requirement: A run recorded before a knob existed
When reuse is planned with today's identity parts, a stored identity that lacks a knob today's settings record SHALL match if filling that knob with its `UNRECORDED` value gives today's digest, and SHALL not match otherwise.

#### Scenario: The missing knob sits at its unrecorded value
- **WHEN** the stored incumbent run lacks a knob that today sits at its unrecorded value
- **THEN** every incumbent cell is reused
Test: tests/test_repo_looks_1353.py::test_a_run_recorded_before_a_knob_at_its_unrecorded_value_is_the_incumbents_exam

#### Scenario: The missing knob's unrecorded value is not today's
- **WHEN** the knob's unrecorded value differs from today's value
- **THEN** no cell is reused
Test: tests/test_repo_looks_1353.py::test_a_missing_knob_whose_unrecorded_value_is_not_todays_is_another_exam

### Requirement: Reused cells join the run
The stored rows a run skipped SHALL join it relabelled as this run's incumbent cells, limited to the cells its checkpoint says it skipped under the planned digest; a stored row that is gone SHALL be reported missing and not counted as reused, and the stored seconds and reply tokens of the reused cells SHALL stand as the incumbent's timing.

#### Scenario: Stored cells pair with the challenger
- **WHEN** a paired run that reused every incumbent cell is merged with its stored rows
- **THEN** the reuse evidence counts every cell and a look sees the run's rows against every holdout cell
Test: tests/test_incumbent_reuse_1094.py::test_the_measure_step_pairs_the_stored_cells_with_the_challenger

#### Scenario: The watchdog times the stored incumbent
- **WHEN** a paired run that reused the incumbent is judged by the watchdog part way through
- **THEN** the incumbent has a cell for every reused cell and the pair can be judged
Test: tests/test_incumbent_reuse_1094.py::test_the_watchdog_judges_the_challenger_against_the_stored_incumbent_time

#### Scenario: A stored row that is gone
- **WHEN** a planned cell's stored row no longer exists
- **THEN** it is listed missing and the reused count drops by one
Test: untested

#### Scenario: A checkpoint under another digest
- **WHEN** the run's checkpoint records no reuse, or reuse under a digest other than the plan's
- **THEN** no stored cell joins the run
Test: untested

### Requirement: Known-answer replay of a paused run
The reuse replay SHALL replay a paused paired run's looks twice from its own rows, once as run and once with each challenger cell's incumbent draw taken from the newest earlier run of the same lane whose recorded conditions match, reading the run's newest pause; it SHALL refuse a run that does not exist or was never paused.

#### Scenario: Draws only from earlier matching runs
- **WHEN** a paused run has an earlier matching run, an earlier run under another reply budget, a later run, and more than one pause
- **THEN** only the earlier matching run supplies draws, and every challenger cell is reused from it
- **AND** the control replay follows the newest pause's looks, and the reuse replay reflects the stored draws
Test: tests/test_incumbent_reuse_1094.py::test_the_replay_takes_draws_only_from_earlier_runs_that_match_and_reads_the_newest_pause

#### Scenario: A run never paused
- **WHEN** the replay is asked for a run with no pause, or no such run
- **THEN** it raises a value error saying so
Test: untested

### Requirement: Served bytes in the identity
A candidate's identity SHALL read the bytes it is served from: for a llama-server spec served from this machine, the binary with its llama.cpp libraries, the model file and the router preset's section; for an mlx spec, the installed `MLX_DISTS` and the model's hub snapshot; anything it cannot read SHALL be named unresolved and leave the digest empty.

#### Scenario: A llama-server spec
- **WHEN** the identity of a llama-server spec is read
- **THEN** it has a digest, nothing unresolved, the binary and its library as runtime and the model file as model
Test: tests/test_incumbent_reuse_1094.py::test_the_served_bytes_are_read_for_a_llama_server_spec

#### Scenario: A missing model file
- **WHEN** the spec's model file is gone
- **THEN** the digest is empty and the unresolved list names the model
Test: tests/test_incumbent_reuse_1094.py::test_a_spec_whose_model_file_is_missing_has_no_digest

#### Scenario: Not a text spec, or not served here
- **WHEN** the spec is not a text spec, or its model is served from another machine
- **THEN** the digest is empty and the reason is named
Test: untested

#### Scenario: A file is hashed once
- **WHEN** a file's digest is asked again with its size and modification time unchanged
- **THEN** the cached digest is returned without reading it
- **AND** once it changes the file is read again and the cache keeps one entry for it
Test: tests/test_incumbent_reuse_1094.py::test_a_file_is_hashed_once_until_its_size_or_mtime_moves

#### Scenario: Bytes that moved
- **WHEN** a stored identity's model bytes differ from what is served now
- **THEN** the change names the part and the file whose bytes changed
Test: tests/test_incumbent_reuse_1094.py::test_reverify_names_a_model_whose_bytes_moved

### Requirement: What the digest matches
The identity digest SHALL cover the served bytes, the settings the spec is sent (reply budget, ladder, sampling, template, method and the exam's knobs), the exam (lane, split version, grader, and the repo harness when it is not the patch harness) and the machine facts that change results; the harness commit SHALL be recorded and never matched, and the `TIMING` facts SHALL be recorded beside it and never matched.

#### Scenario: Any served or sent input changes
- **WHEN** the binary, a library, the model file, the preset section, the sampling or the split version changes
- **THEN** the digest moves
Test: tests/test_incumbent_reuse_1094.py::test_the_digest_moves_when_any_served_or_sent_input_changes

#### Scenario: Reply budget, spec options, knobs and machine
- **WHEN** the reply budget, a spec option, a knob, the hardware model, the OS build, the memory or the power mode differs
- **THEN** the digest differs in every case
Test: tests/test_incumbent_reuse_1094.py::test_the_digest_moves_with_the_reply_budget_knobs_and_machine

#### Scenario: The harness commit
- **WHEN** only the harness commit or its dirty diff differs
- **THEN** the digest and per-case digests are unchanged and the new commit is recorded
Test: tests/test_incumbent_reuse_1094.py::test_the_harness_commit_is_recorded_and_never_matched

#### Scenario: Swap, free memory and thermal state
- **WHEN** only swap use, free memory or thermal state differs
- **THEN** the digest is unchanged and the timing records the new value
Test: tests/test_incumbent_reuse_1094.py::test_the_digest_holds_when_only_swap_or_free_memory_or_thermal_change

#### Scenario: Repair knobs only under the repair harness
- **WHEN** the repo lane's settings are read under the patch harness and under the repair harness
- **THEN** the patch settings carry none of the repair knobs and the repair settings carry all of them
Test: tests/test_repo_repair_890.py::test_patch_settings_carry_no_repair_knob_and_repair_settings_carry_all

#### Scenario: A repair harness is another exam
- **WHEN** a repo identity is computed under the patch harness and under the repair harness with the same settings
- **THEN** both digests resolve and differ, and only the repair exam part names its harness
Test: tests/test_repo_repair_890.py::test_a_repair_identity_never_matches_a_patch_identity

### Requirement: Per-case digests
Each case SHALL have its own digest over its content, its case file's bytes and, for a text spec, the request body it is sent less the model name, so a change to one case or to how it is asked moves that case's digest without moving the run's.

#### Scenario: Hidden tests, case file and harness prompt
- **WHEN** a case's hidden tests, its file's bytes, or the system prompt the harness sends change
- **THEN** that case's digest moves
- **AND** a system prompt change leaves the run's digest unchanged
Test: tests/test_incumbent_reuse_1094.py::test_a_case_digest_moves_with_its_hidden_tests_its_file_and_the_prompt_the_harness_sends

#### Scenario: How a repo case is asked
- **WHEN** the way repo cases are asked changes
- **THEN** every such case's request digest moves
Test: tests/test_repo_no_tools_1129.py::test_every_cases_request_digest_moves

#### Scenario: A session case's quotation
- **WHEN** a session case is no longer quoted
- **THEN** its digest moves
Test: tests/test_repo_no_tools_1129.py::test_a_session_cases_request_digest_covers_its_quotation

### Requirement: Grader digest
The grader digest SHALL hash, without importing anything, each top-level statement of the `GRADER_PACKAGES` modules that the lane's entry in `CHECKER_REGISTRY` and the `SCORE_ENTRY` reach by static import and name analysis, and list the modules reached; a statement outside that closure SHALL not move it, and a lane with no registry entry SHALL have an empty grader digest.

#### Scenario: A module outside the closure
- **WHEN** an unrelated module, a module only an unreached function imports, or another lane's checker is edited
- **THEN** the grader digest is unchanged and lists only the reached modules
Test: tests/test_incumbent_reuse_1094.py::test_a_module_outside_the_import_closure_keeps_the_grader_digest

#### Scenario: A module two imports below the checker
- **WHEN** a module the grader imports lazily is edited
- **THEN** the grader digest moves
Test: tests/test_incumbent_reuse_1094.py::test_editing_a_module_two_imports_below_the_checker_moves_the_grader_digest

#### Scenario: The grader or the lane's checker
- **WHEN** the grader module or the lane's checker is edited
- **THEN** the grader digest moves each time
Test: tests/test_incumbent_reuse_1094.py::test_editing_the_grader_or_the_lane_checker_moves_the_grader_digest

#### Scenario: The code lane
- **WHEN** the code lane's exam is read twice
- **THEN** it is the same both times, lists the core scorer, the code checks, their base and the failure reasons, and no other check module
Test: tests/test_incumbent_reuse_1094.py::test_the_code_lane_digest_is_stable_and_lists_its_modules

### Requirement: soh verify runs each lane's own default
`soh verify` SHALL plan the lanes that need a receipt (one lane with `--lane`, every lane with `--all`), print each with its cost and reason, run nothing without `--run`, and with `--run` SHALL run each runnable lane in its own new run directory, read its verdict from the store by that path, and exit 1 when any lane is broken; with nothing to plan it SHALL list parked lanes as parked, not as verified.

#### Scenario: Nothing to plan
- **WHEN** every lane that should run has a recent receipt and one lane is parked
- **THEN** it says so, names the parked lane and its reason, and exits 0
Test: untested

#### Scenario: A plan without --run
- **WHEN** lanes are planned and `--run` is absent
- **THEN** nothing runs and the output says `--run` spends it
Test: untested

#### Scenario: A broken lane
- **WHEN** a lane's run exits non-zero or its default passes nothing
- **THEN** it is reported broken and the command exits 1
Test: untested

### Requirement: soh throughput
`soh throughput` SHALL refuse to run without `--texts`, `--claims` or `--code`, refuse `--serve` for a model that is not a vLLM spec, default the reply budget to the lane's (code, claims, else `completion.MAX_TOKENS`), hold the eval lock for the sweep's own bound plus any vLLM start, start and stop the named vLLM engine around the sweep, pass its request timeout to the sweep, and emit one object naming the model, engine and levels.

#### Scenario: A command
- **WHEN** `soh throughput --model M --texts F --levels L` is parsed
- **THEN** it dispatches to `cmd_throughput` with those levels
Test: tests/test_throughput.py::test_lh_throughput_is_a_command

#### Scenario: No inputs
- **WHEN** neither texts, claims nor code is given
- **THEN** it exits non-zero
Test: tests/test_throughput.py::test_throughput_refuses_neither_texts_nor_claims

#### Scenario: --serve with another spec
- **WHEN** `--serve` is given for a non-vLLM model
- **THEN** it exits non-zero
Test: tests/test_vllm.py::test_serve_needs_a_vllm_spec

#### Scenario: The engine is served for the sweep
- **WHEN** `--serve` names a vLLM engine
- **THEN** the engine starts before the sweep and stops after, and the output names that engine
Test: tests/test_vllm.py::test_soh_throughput_serves_the_engine_for_the_sweep_and_stops_it

#### Scenario: A vLLM spec without --serve
- **WHEN** a vLLM spec is swept against a running engine
- **THEN** the output names its engine and the requests carry the bare model
Test: tests/test_vllm.py::test_soh_throughput_routes_a_vllm_spec_and_labels_the_engine

#### Scenario: The lock's bound
- **WHEN** a sweep is run with a request timeout
- **THEN** the eval lock is declared with the sweep's own deadline
Test: tests/test_lock_deadlines_775.py::test_measure_throughput_declares_the_sweep_it_runs

#### Scenario: The request timeout
- **WHEN** `--timeout` is given
- **THEN** the sweep gets that timeout
Test: tests/test_throughput.py::test_throughput_passes_its_request_timeout_to_the_sweep

#### Scenario: One object
- **WHEN** it runs with `--json`
- **THEN** stdout is one object whose levels carry the sweep's rows
Test: tests/test_json_everywhere.py::test_throughput_is_one_object

### Requirement: soh reuse-replay checks a past verdict read-only
`soh reuse-replay RUN` SHALL replay a stored paired run's looks with and without the incumbent's draws from earlier matching runs, reading the live store read-only or a given store copy opened immutable, print both walks, and exit 0 when both reach the same adopt decision or neither reaches one, and 1 otherwise; a run it cannot replay SHALL be an error.

#### Scenario: The same verdict
- **WHEN** control and replay reach the same adopt and decision, or neither reaches a verdict
- **THEN** it prints "same verdict" and exits 0
Test: tests/test_incumbent_reuse_1094.py::test_reuse_replay_exits_1_only_when_the_verdict_moves

#### Scenario: A moved verdict
- **WHEN** the replay reaches another decision, or only one walk reaches a verdict
- **THEN** it prints "VERDICT MOVED" and exits 1
Test: tests/test_incumbent_reuse_1094.py::test_reuse_replay_exits_1_only_when_the_verdict_moves

#### Scenario: A store copy
- **WHEN** `--store` names a copy
- **THEN** the copy is opened immutable and the live store is not opened
Test: untested
