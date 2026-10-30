# Watchdog Specification

## Purpose
A periodic process outside the jobs it watches: each wake it observes this machine, judges what it sees against a declared criteria table, acts from a fixed action set (or only says what it would do), and records every finding.

## Requirements

### Requirement: Periodic single wake
The watchdog SHALL run as a launchd agent on every machine role, waking on a calendar every few minutes, and SHALL let only one wake run at a time on a machine; requests it sends SHALL carry the purpose `watchdog`.

#### Scenario: Calendar schedule
- **WHEN** the launchd units are generated
- **THEN** the watchdog unit runs `serve-watchdog.sh` on minutes 0 to 55 in steps of 5, with no hour, no StartInterval and no RunAtLoad
Test: tests/test_launchd.py::test_the_watchdog_wakes_every_few_minutes_on_a_calendar

#### Scenario: A node keeps the watchdog
- **WHEN** the units are generated for the node role
- **THEN** the watchdog unit is present while the discover and audit units are not
Test: tests/test_launchd.py::test_a_node_keeps_the_watchdog_because_it_watches_this_machine

#### Scenario: A deploy does not kill a running wake
- **WHEN** an install runs while a watchdog wake is running
- **THEN** the watchdog unit is not booted out and the install reports it as deferred
Test: tests/test_launchd.py::test_install_does_not_kill_a_watchdog_wake_that_is_running

#### Scenario: A second wake while one holds the lock
- **WHEN** a wake starts while another wake holds the watchdog's lock file
- **THEN** it returns busy at once and records nothing
Test: tests/test_watchdog.py::test_a_second_wake_while_one_holds_the_lock_does_nothing

#### Scenario: Purpose tag
- **WHEN** the watchdog command runs
- **THEN** the process purpose is `watchdog`
Test: tests/test_purpose_825.py::test_the_watchdog_sends_watchdog

### Requirement: Dry run unless enabled
The watchdog SHALL act only when `LH_WATCHDOG_ACT` is exactly `1` or `--act` is given, and `--dry-run` SHALL override both; in a dry run it SHALL print and record what it would do (outcome `dry-run`) and take no action.

#### Scenario: The switch must be exactly 1
- **WHEN** the environment has no switch, or `LH_WATCHDOG_ACT=yes`
- **THEN** the watchdog is not acting
- **AND** with `LH_WATCHDOG_ACT=1` it is acting
Test: tests/test_watchdog.py::test_acting_needs_the_env_switch_or_the_flag

#### Scenario: A dry-run wake
- **WHEN** a dry-run wake finds an orphan
- **THEN** no hand is called, the row has action `reap`, `dry_run` 1 and outcome `dry-run`
- **AND** the log line starts `[dry-run] would reap`
Test: tests/test_watchdog.py::test_a_dry_run_records_what_it_would_do_and_does_nothing

#### Scenario: A dry-run notify shows nothing
- **WHEN** a dry-run wake judges a criterion whose action is notify
- **THEN** no desktop notification is posted and the row records notify with outcome `dry-run`
Test: tests/test_watchdog.py::test_a_dry_run_records_the_notify_and_shows_nothing

#### Scenario: The install keeps the switch
- **WHEN** the units are generated once with `LH_WATCHDOG_ACT=1` and again without it
- **THEN** the watchdog unit keeps `LH_WATCHDOG_ACT=1` and no other unit gets it
Test: tests/test_launchd.py::test_the_watchdog_acts_only_once_enabled_and_keeps_the_switch

#### Scenario: --dry-run beats the switch
- **WHEN** `LH_WATCHDOG_ACT=1` is set and `--dry-run` is given
- **THEN** the wake runs as a dry run
Test: untested

### Requirement: Positive identification
The watchdog SHALL judge only subjects it identified as SoHoT's own: the discover agent (the launchd discover pid whose command is the discover loop), a work queue job (a pid file naming its group leader), and an evals.run group owned by one of those, writing a progress file, or reparented to launchd; any other evals.run SHALL be listed as left alone and never judged.

#### Scenario: An eval under a queue job
- **WHEN** an evals.run group descends from a queue job's leader
- **THEN** the job is the only top-level subject and the eval is its child, owned by that job, with its own group
Test: tests/test_watchdog.py::test_an_eval_under_a_queue_job_is_that_job_s_child_and_not_a_top_level_subject

#### Scenario: An eval started in a terminal
- **WHEN** an evals.run runs under a shell with no queue job, discover agent or progress file
- **THEN** it is listed as unowned and no finding is made on it
Test: tests/test_watchdog.py::test_an_eval_a_person_started_in_a_terminal_is_left_alone

#### Scenario: The discover pid must run the discover loop
- **WHEN** launchd names a discover pid whose command is something else
- **THEN** no discover subject is made
Test: tests/test_watchdog.py::test_the_discover_agent_is_identified_by_launchd_pid_and_its_command

#### Scenario: Long command lines are read whole
- **WHEN** a process has a command line longer than the terminal width
- **THEN** the process listing keeps the tail of its argv
Test: tests/test_ps_width_1065.py::test_the_watchdog_listing_keeps_the_tail_of_a_long_argv_at_80_columns

#### Scenario: Elapsed times in every ps form
- **WHEN** ps prints elapsed time as mm:ss or dd-hh:mm:ss, or prints an unparsable line
- **THEN** each is read in seconds and the bad line is skipped
Test: tests/test_watchdog.py::test_ps_output_parses_elapsed_times_in_every_form

#### Scenario: The eval and loop patterns match the sweep guard's
- **WHEN** the watchdog and the sweep guard recognise an evals.run or a discover loop
- **THEN** they use the same eval pattern and both match the loop command
Test: tests/test_sweep_guard_1000.py::test_the_guard_reads_what_the_harness_writes

### Requirement: Signal only groups that are wholly SoHoT's
The watchdog SHALL signal a process group only when every live member is SoHoT's (an eval group of evals.run processes only, or a queue job's group), and stop and reap SHALL refuse a subject without such a group.

#### Scenario: A mixed group
- **WHEN** an eval's process group also holds a non-eval process
- **THEN** the eval subject has no signalable group
Test: tests/test_watchdog.py::test_a_group_with_anything_but_evals_in_it_cannot_be_signalled

#### Scenario: Stop without a group
- **WHEN** stop is asked for a subject with no group of ours
- **THEN** the outcome starts `refused`
Test: tests/test_watchdog.py::test_stop_refuses_a_subject_with_no_group_of_ours

#### Scenario: Stop terminates the group
- **WHEN** stop is asked for a subject with a group
- **THEN** the group is sent TERM, then KILL after the stop grace, and the outcome names the group
Test: tests/test_watchdog.py::test_stop_terminates_a_fake_process_group

### Requirement: Missing inputs skip a criterion
The watchdog SHALL skip each criterion whose needed observation could not be made, recording why, and SHALL treat an observation that raises as a gap rather than a lost wake.

#### Scenario: No progress file
- **WHEN** no running eval has written a progress file
- **THEN** overrun and no_progress are skipped with a reason naming the progress file, and long_run is still judged
Test: tests/test_watchdog.py::test_criteria_that_need_a_progress_file_are_skipped_and_say_so_without_one

#### Scenario: Unreadable served models
- **WHEN** reading the served models raises
- **THEN** idle_unload is skipped with the error as its reason and the wake goes on
Test: tests/test_idle_unload_1157.py::test_an_unreadable_server_is_a_gap_not_a_lost_wake

#### Scenario: No mcp unit
- **WHEN** no mcp unit is loaded
- **THEN** stale_mcp is skipped and says no mcp unit is loaded
Test: tests/test_mcp_orphans_1155.py::test_with_no_mcp_unit_the_criterion_is_skipped_and_says_why

#### Scenario: Unreadable day clearance
- **WHEN** reading the day clearance raises
- **THEN** the gap is recorded and no clearance is in force, so the day limits stand
Test: untested

### Requirement: A fixed criteria table and action set
The watchdog SHALL judge only the criteria in its table, each mapping to a first action and a different escalation drawn from the fixed set note, notify, file, pause, stop, reap, unload, restart, with its thresholds in registered knobs; the mapping SHALL be long_run notify then pause, overrun file then stop, no_progress notify then stop, orphan reap then file, stale_mcp notify then file, daytime_gpu pause then stop, day_clear note then notify, idle_lock note then file, idle_model note then unload, idle_unload unload then notify, memory notify then pause, memory_warn notify then unload, gateway_down notify then restart, mlx_dead restart then notify, node_fallbacks notify then file.

#### Scenario: Table integrity
- **WHEN** the criteria table is loaded
- **THEN** ids are unique, every action and escalation is in the fixed set and differs, every named knob is registered, and every action in the set is used
Test: tests/test_watchdog.py::test_every_criterion_maps_to_actions_from_the_fixed_set_and_names_registered_knobs

#### Scenario: An action outside the set
- **WHEN** a hand is asked for an action not in the set
- **THEN** it raises and does nothing
Test: tests/test_watchdog.py::test_an_action_outside_the_fixed_set_is_refused

#### Scenario: One failed action does not end the wake
- **WHEN** an action raises
- **THEN** its outcome is recorded as `<action> failed: ...` and the remaining findings are still acted on
Test: untested

### Requirement: Escalation on repeat
The watchdog SHALL take a criterion's escalation instead of its first action when at least `ESCALATE_AFTER` earlier rows of the same criterion, subject, dry-run state and machine fall inside `ESCALATE_WINDOW_S`.

#### Scenario: The third trip escalates
- **WHEN** an orphan is found on three acting wakes inside the window
- **THEN** the first two reap and the third files, marked escalated
Test: tests/test_watchdog.py::test_acting_records_the_outcome_and_escalates_on_repeat

#### Scenario: Trips spread past the window
- **WHEN** the same trips are each more than the window apart
- **THEN** every one takes the first action
Test: tests/test_watchdog.py::test_trips_outside_the_window_do_not_escalate

#### Scenario: Dry-run trips do not count
- **WHEN** dry-run wakes tripped a criterion and then an acting wake trips it
- **THEN** the acting wake takes the first action
Test: tests/test_watchdog.py::test_dry_run_trips_never_escalate_a_real_action

### Requirement: Every finding is recorded
The watchdog SHALL insert one `watchdog_actions` row per finding with time, machine, criterion, subject, action, escalated, dry_run, outcome and evidence that adds how the subject was identified, pid, pgid, command, owner and a fingerprint stable across pids.

#### Scenario: Evidence carries identification
- **WHEN** a finding is recorded
- **THEN** its evidence holds `identified_by`, the pgid and a fingerprint
Test: tests/test_watchdog.py::test_a_dry_run_records_what_it_would_do_and_does_nothing

#### Scenario: Fingerprint stability
- **WHEN** the same criterion trips on the same kind of command with different pids
- **THEN** the fingerprints are equal, and a different criterion gives a different one
Test: tests/test_watchdog.py::test_the_fingerprint_survives_a_new_pid_and_changes_with_the_criterion

### Requirement: long_run
The watchdog SHALL find long_run on each non-orphan top-level subject whose elapsed time exceeds `LONG_RUN_DAY_S` (2 h) inside the day hours or `LONG_RUN_S` (8 h) outside them, one limit for every subject kind.

#### Scenario: Night limit
- **WHEN** a job has run just past the night limit at night
- **THEN** long_run trips, and just under it does not
Test: tests/test_watchdog.py::test_long_run_trips_past_the_night_limit_and_not_before

#### Scenario: Tighter by day
- **WHEN** a job has run just past the day limit
- **THEN** long_run trips at noon and not at night
Test: tests/test_watchdog.py::test_long_run_is_tighter_during_the_day

### Requirement: overrun
The watchdog SHALL find overrun on an eval with at least `OVERRUN_MIN_CASES` (3) cases done when a candidate's observed seconds per case exceed `OVERRUN_FACTOR` (2) times its plan; in a paired run a challenger SHALL instead be judged against the incumbent on at least `OVERRUN_MIN_PAIRS` (5) shared cases, per reply token when both have token counts and per second otherwise, against the plan's ratio, including incumbent cells taken from stored draws.

#### Scenario: Over and under the factor
- **WHEN** a single-candidate eval's observed rate is just over, or just under, the factor times its plan
- **THEN** overrun trips naming the candidate, or does not
Test: tests/test_watchdog.py::test_overrun_trips_at_the_factor_over_plan_and_not_under_it

#### Scenario: Too few cases
- **WHEN** fewer than the minimum cases are done
- **THEN** overrun does not trip however slow
Test: tests/test_watchdog.py::test_overrun_waits_for_enough_cases

#### Scenario: Slower per token on the same cases
- **WHEN** a challenger takes three times the seconds per reply token on paired cases
- **THEN** overrun trips with basis `seconds per reply token` and the pair count
Test: tests/test_overrun_864.py::test_a_challenger_three_times_slower_per_token_on_the_same_cases_is_an_overrun

#### Scenario: More tokens at the same speed
- **WHEN** a challenger writes three times the tokens at the same speed
- **THEN** overrun does not trip
Test: tests/test_overrun_864.py::test_a_challenger_that_writes_three_times_the_tokens_at_the_same_speed_is_not

#### Scenario: No token counts
- **WHEN** rows carry no token counts
- **THEN** paired seconds are compared, with basis `seconds`
Test: tests/test_overrun_864.py::test_without_token_counts_the_paired_seconds_are_compared

#### Scenario: Too few pairs
- **WHEN** fewer than the minimum cases are paired
- **THEN** the challenger is not judged
Test: tests/test_overrun_864.py::test_a_challenger_is_not_judged_before_enough_cases_are_paired

#### Scenario: The incumbent keeps its own plan
- **WHEN** the incumbent of a paired run is far over its own plan
- **THEN** overrun trips on the incumbent
Test: tests/test_overrun_864.py::test_the_incumbent_of_a_paired_run_is_still_judged_against_its_own_plan

#### Scenario: Reused incumbent cells
- **WHEN** a paired run reuses the incumbent's stored draws
- **THEN** the incumbent's stored times form the pairs
Test: tests/test_incumbent_reuse_1094.py::test_the_watchdog_judges_the_challenger_against_the_stored_incumbent_time

### Requirement: no_progress
The watchdog SHALL find no_progress on an eval whose last finished case (or start) is older than the larger of `STALL_S` (1800 s) and `STALL_CASES` (10) planned cases.

#### Scenario: Stalled and moving
- **WHEN** no case finished for longer than the stall time
- **THEN** no_progress trips, and a run that finished a case a minute ago does not
Test: tests/test_watchdog.py::test_no_progress_trips_when_no_case_finished_for_the_stall_time

#### Scenario: A slow plan gets its planned cases
- **WHEN** ten planned cases take longer than the stall time
- **THEN** that longer limit applies
Test: tests/test_watchdog.py::test_no_progress_allows_a_slow_plan_its_planned_cases

### Requirement: orphan
The watchdog SHALL find orphan on a top-level subject at least `ORPHAN_GRACE_S` (120 s) old that is an unowned evals.run reparented to launchd or a queue job whose worker is not running or whose row is not running, and reap SHALL refuse a subject not marked orphan.

#### Scenario: A reparented eval
- **WHEN** an evals.run with parent 1 is past the grace, or inside it
- **THEN** orphan trips, or does not
Test: tests/test_watchdog.py::test_an_eval_reparented_to_launchd_is_an_orphan_once_past_the_grace

#### Scenario: A queue job with no worker or a settled row
- **WHEN** a job's group is alive with no worker running, or with its row cancelled
- **THEN** orphan trips, and with a running worker and row it does not
Test: tests/test_watchdog.py::test_a_queue_job_with_no_worker_or_a_settled_row_is_an_orphan

#### Scenario: Reap only an orphan
- **WHEN** reap is asked for a group not marked orphan, then for one marked orphan
- **THEN** the first is refused and left running, the second is terminated
Test: tests/test_watchdog.py::test_reap_kills_an_orphan_group_and_refuses_one_that_is_not

### Requirement: daytime_gpu
Inside the day hours [`DAY_START_HOUR`, `DAY_END_HOUR`) (local hours), the watchdog SHALL find daytime_gpu on every non-orphan top-level subject past `DAYTIME_GPU_S`, whatever it runs, except a subject whose evals all hold a cloud slot while it holds no GPU lock.

#### Scenario: Day and night
- **WHEN** a job has run past the limit
- **THEN** daytime_gpu trips at noon and not at night, and a job under the limit does not trip at noon
Test: tests/test_watchdog.py::test_daytime_gpu_trips_inside_the_day_and_not_at_night

#### Scenario: Any job kind trips
- **WHEN** two jobs are past the limit in the day with no clearance, one running an eval and one running another command
- **THEN** both trip daytime_gpu
Test: tests/test_day_clear_1112.py::test_without_a_clearance_the_day_limit_pauses_them

#### Scenario: A cloud-only job
- **WHEN** a job's eval holds a cloud slot and the job holds no GPU lock
- **THEN** daytime_gpu does not trip, and it does when the job also holds the eval lock
Test: tests/test_cloud_lock_1135.py::test_the_watchdog_does_not_pause_a_cloud_job_for_daytime_gpu

#### Scenario: A job with no progress file is stopped
- **WHEN** daytime_gpu trips on a job with no progress file on three wakes inside the window
- **THEN** the two pauses are unavailable and the third trip stops its group
Test: untested

### Requirement: Day clearance
A day clearance SHALL be one machine-wide store row, given with who and why, in force from when it is given until today's `DAY_END_HOUR`; while one is in force inside the day hours the watchdog SHALL skip daytime_gpu and long_run and record one day_clear finding per subject per day limit it is past, and SHALL never lift anything outside the day hours or any other criterion.

#### Scenario: Every job let off both limits
- **WHEN** two jobs are past both day limits under a clearance
- **THEN** neither daytime_gpu nor long_run trips, and four day_clear findings carry the clearance text
Test: tests/test_day_clear_1112.py::test_a_clearance_lets_every_job_past_both_day_limits_and_names_each_skip

#### Scenario: Never at night
- **WHEN** a clearance is in force at night and jobs are past the night limit
- **THEN** long_run trips and no day_clear finding is made
Test: tests/test_day_clear_1112.py::test_a_clearance_never_lifts_the_night_limit

#### Scenario: A stuck job is still caught
- **WHEN** a cleared job's eval has made no progress past the stall time
- **THEN** no_progress trips while daytime_gpu does not
Test: tests/test_day_clear_1112.py::test_a_stuck_job_is_still_caught_under_a_clearance

#### Scenario: Expiry, revoke and refusals
- **WHEN** a clearance is given at 11:30
- **THEN** it holds until 21:00 that day and not after or the next day, revoke ends it early, and giving one after day end or with blank words is refused
Test: tests/test_day_clear_1112.py::test_the_store_clearance_expires_at_day_end_and_revoke_ends_it

#### Scenario: The latest clearance and revoking all
- **WHEN** two clearances are given and then revoked
- **THEN** the later text shows while in force and none remains after revoke
Test: tests/test_day_clear_1112.py::test_a_second_clearance_is_revoked_with_the_first_and_shows_the_latest_text

#### Scenario: A wake under a stored clearance
- **WHEN** acting wakes run under a stored clearance and then after revoke
- **THEN** each skip is a day_clear row, noted then notified on repeat, and after revoke the job is paused by daytime_gpu
Test: tests/test_day_clear_1112.py::test_a_wake_reads_the_store_clearance_records_each_skip_and_at_most_notifies

#### Scenario: The day command
- **WHEN** `soh day status`, `soh day clear "<words>"` and `soh day revoke` run
- **THEN** status says there is none, clear records and shows it until 21:00, revoke ends it, and clear without words fails
Test: tests/test_day_clear_1112.py::test_the_cli_clears_shows_and_revokes

### Requirement: idle_lock
The watchdog SHALL find idle_lock when the eval lock is held, no top-level subject is running, and the holder's `since` is at least `IDLE_HOLD_S` old or unknown.

#### Scenario: Old, fresh and busy
- **WHEN** the lock has been held past the limit with nothing running
- **THEN** idle_lock trips, and a fresh hold or a running job does not trip it
Test: tests/test_watchdog.py::test_idle_lock_trips_only_when_nothing_runs_and_it_is_old

#### Scenario: A holder with no start time
- **WHEN** the holder record has no `since` and nothing is running
- **THEN** idle_lock trips on the first wake
Test: untested

### Requirement: idle_model
With nothing running, the watchdog SHALL find idle_model on each router-resident model that no lane, adoption or alias protects, and its unload SHALL go through the router's own release and protection.

#### Scenario: Resident with nothing running
- **WHEN** an unprotected model is resident and nothing runs
- **THEN** idle_model trips, and not while a job runs or with nothing resident
Test: tests/test_watchdog.py::test_idle_model_trips_on_an_unprotected_resident_model_with_nothing_running

#### Scenario: Unload through the router
- **WHEN** unload is taken for idle_model
- **THEN** the router releases the stem, and when it keeps it the outcome starts `kept`
Test: tests/test_watchdog.py::test_unload_goes_through_the_router_s_own_protection

### Requirement: idle_unload
The watchdog SHALL find idle_unload on each loaded router model and each mlx model other than its boot model that has no request in flight and has been idle at least `IDLE_UNLOAD_DAY_S` inside the day hours or the router's own idle sleep (`SERVE_IDLE_UNLOAD_S`) outside them; idle time SHALL start at the latest of the residency first seen, the last wake a running eval named it (or an eval had no progress file, or a request was in flight), and its last request other than watchdog or smoke traffic; the unload SHALL give back lane and adopted models too.

#### Scenario: Day limit
- **WHEN** a loaded model's last request is exactly the day limit ago at noon
- **THEN** idle_unload trips with server, model, idle seconds, limit and day, and one second less does not
Test: tests/test_idle_unload_1157.py::test_a_lane_model_with_no_request_past_the_day_limit_is_given_back

#### Scenario: Night limit
- **WHEN** it is night
- **THEN** the limit is the router's sleep, longer than the day limit
Test: tests/test_idle_unload_1157.py::test_at_night_the_limit_is_the_router_s_own_sleep

#### Scenario: Pinned by a running eval
- **WHEN** a running eval's specs name the model
- **THEN** it is kept, and its idle time starts from the last wake that saw it named
Test: tests/test_idle_unload_1157.py::test_a_model_a_running_eval_names_is_pinned_and_its_clock_starts_when_the_run_ends

#### Scenario: Unknown use is not idle
- **WHEN** a running eval has no progress file
- **THEN** no model is idle
Test: tests/test_idle_unload_1157.py::test_an_eval_with_no_progress_file_makes_nothing_idle

#### Scenario: Another model while an eval runs
- **WHEN** an eval runs naming a different model
- **THEN** the unnamed idle model is still given back
Test: tests/test_idle_unload_1157.py::test_another_model_is_given_back_while_an_eval_runs

#### Scenario: In flight or unknown
- **WHEN** a request is in flight or the in-flight state is unknown
- **THEN** the model is kept
Test: tests/test_idle_unload_1157.py::test_a_request_in_flight_or_an_unknown_one_keeps_the_model

#### Scenario: First seen now
- **WHEN** a model is first seen loaded this wake
- **THEN** it waits a whole limit before it trips
Test: tests/test_idle_unload_1157.py::test_a_model_first_seen_now_waits_a_whole_limit

#### Scenario: A residency that ended
- **WHEN** a model was unloaded and is loaded again
- **THEN** its idle time starts over
Test: tests/test_idle_unload_1157.py::test_a_residency_that_ended_starts_over

#### Scenario: Probe and smoke traffic
- **WHEN** the only recent requests to a model are tagged watchdog or smoke
- **THEN** they do not count as use
Test: tests/test_idle_unload_1157.py::test_probe_and_smoke_requests_are_not_use

#### Scenario: What counts as served
- **WHEN** the router lists loaded, sleeping, busy and unprobeable models and mlx holds a non-boot model
- **THEN** loaded router models and the non-boot mlx model are served, each with in-flight true, false or unknown
Test: tests/test_idle_unload_1157.py::test_the_served_probe_reads_loaded_router_models_their_slots_and_a_non_boot_mlx_model

#### Scenario: Unload past the eval lock
- **WHEN** unload is taken for idle_unload
- **THEN** the router releases with no kept set and as proven idle, and mlx releases with no kept set
Test: tests/test_idle_unload_1157.py::test_unload_gives_back_a_lane_s_own_model_past_the_eval_lock

#### Scenario: An unload that did not take
- **WHEN** the same idle spell trips on four wakes
- **THEN** the first two unload and the next two notify
Test: tests/test_idle_unload_1157.py::test_a_wake_records_the_unload_and_one_that_does_not_take_is_notified

#### Scenario: A new spell
- **WHEN** a new request starts a new idle spell
- **THEN** the subject key changes, so it is unloaded afresh, while the fingerprint stays
Test: tests/test_idle_unload_1157.py::test_a_new_request_starts_a_new_spell_that_is_unloaded_afresh

#### Scenario: Evidence for the limits
- **WHEN** request spans are priced against a limit
- **THEN** each gap past the limit costs one load and each gap counts as idle loaded time up to the limit
Test: tests/test_idle_unload_1157.py::test_a_limit_costs_a_load_per_gap_past_it_and_idle_hours_up_to_it

### Requirement: memory
While a job runs, the watchdog SHALL find memory on each non-orphan top-level subject when swapouts between wakes exceed `SWAPOUT_MAX_PER_MIN` (2000 per minute) or pressure is critical.

#### Scenario: Critical pressure
- **WHEN** pressure is critical while a job runs
- **THEN** memory trips; with nothing running, or calm, it does not
Test: tests/test_watchdog.py::test_memory_trips_on_alarming_pressure_while_a_job_runs

#### Scenario: Swap growth between wakes
- **WHEN** the swapout counter grows faster than the limit since the last wake
- **THEN** memory trips, and the first wake (no earlier counter) and a slow growth do not
Test: tests/test_watchdog.py::test_memory_trips_on_swap_growth_between_wakes

#### Scenario: Critical with no swapping pauses
- **WHEN** pressure is critical with no swapping on three wakes
- **THEN** memory notifies twice then pauses
Test: tests/test_memory_warn_1082.py::test_critical_pressure_pauses_with_no_swapping

#### Scenario: Swapping still pauses
- **WHEN** swapouts exceed the limit on successive wakes
- **THEN** memory notifies then pauses
Test: tests/test_memory_warn_1082.py::test_swapouts_over_the_limit_still_pause

### Requirement: memory_warn
While a job runs, the watchdog SHALL find memory_warn when pressure is at warn with neither swapping nor critical pressure (an unknown swap rate counts as not swapping), and its escalation SHALL give back idle models (router residents and an unprotected mlx model that no running eval names) and SHALL never pause.

#### Scenario: Notify then unload, never pause
- **WHEN** pressure stays at warn with no swapping for five wakes
- **THEN** memory_warn notifies twice then unloads, no row pauses, and the evidence names the idle mlx model
Test: tests/test_memory_warn_1082.py::test_warn_with_no_swapping_notifies_then_unloads_and_never_pauses

#### Scenario: Unknown swap rate
- **WHEN** the swap rate is unknown
- **THEN** it is read as not swapping
Test: tests/test_memory_warn_1082.py::test_warn_with_an_unknown_swap_rate_is_not_read_as_swapping

#### Scenario: Used or served models are never idle
- **WHEN** the mlx model is protected, named by a running eval, or absent
- **THEN** it is not idle, and an unprotected unnamed router resident is
Test: tests/test_memory_warn_1082.py::test_a_model_a_running_eval_uses_or_a_lane_serves_is_never_idle

#### Scenario: An eval with no progress file
- **WHEN** a running eval has no progress file
- **THEN** nothing is idle
Test: tests/test_memory_warn_1082.py::test_an_eval_with_no_progress_file_makes_nothing_idle

#### Scenario: Unload each idle model
- **WHEN** unload is taken for memory_warn
- **THEN** each idle router model is released as proven idle and each idle mlx model is swapped back, and with none idle the outcome says so
Test: tests/test_memory_warn_1082.py::test_unload_on_warn_releases_each_idle_model_past_the_eval_lock

### Requirement: gateway_down
The watchdog SHALL find gateway_down when the loaded gateway unit's liveliness probe fails, and its restart SHALL run `launchd.sh restart gateway`, report a restart still waiting on the GPU lock after `RESTART_TIMEOUT_S` (180 s), and refuse any service other than the gateway and mlx.

#### Scenario: Failed, healthy and unloaded
- **WHEN** the probe fails, succeeds, or no gateway unit is loaded
- **THEN** gateway_down trips, does not, or is skipped
Test: tests/test_watchdog.py::test_gateway_down_trips_only_on_a_failed_probe

#### Scenario: Restart and refusal
- **WHEN** restart is taken for the gateway, then for another service
- **THEN** the gateway is restarted through launchd.sh and the other is refused without a call
Test: tests/test_watchdog.py::test_restart_runs_launchd_restart_for_the_gateway_and_refuses_an_unlisted_service

#### Scenario: Waiting on the GPU lock
- **WHEN** the restart times out
- **THEN** the outcome says it is still waiting
Test: tests/test_watchdog.py::test_restart_that_waits_on_the_gpu_lock_says_so

### Requirement: mlx_dead
The watchdog SHALL find mlx_dead when the loaded mlx unit answers its health check with 503, and SHALL restart it with `launchctl kickstart -k` without taking the GPU lock; a server that does not answer SHALL be a gap, never a restart, and a restart off macOS SHALL be refused.

#### Scenario: A dead generation thread
- **WHEN** the mlx health answers 503 on an acting wake
- **THEN** the unit is kickstarted and the row records restart with outcome `restarted mlx`
Test: tests/test_mlx_dead_912.py::test_a_stub_server_that_says_its_generation_thread_died_is_restarted_by_the_watchdog

#### Scenario: Healthy or unloaded
- **WHEN** the server is healthy, or the unit is not loaded
- **THEN** nothing is acted on, and with no unit mlx_dead is skipped
Test: tests/test_mlx_dead_912.py::test_a_healthy_or_unloaded_mlx_unit_is_left_alone

#### Scenario: No answer
- **WHEN** the mlx server refuses the connection
- **THEN** mlx_dead is skipped and nothing is restarted
Test: tests/test_mlx_dead_912.py::test_a_server_that_does_not_answer_is_not_restarted

#### Scenario: A restart that did not fix it
- **WHEN** the server stays dead for three wakes
- **THEN** the third trip notifies, escalated
Test: tests/test_mlx_dead_912.py::test_a_restart_that_did_not_fix_it_escalates_to_a_person

#### Scenario: Off macOS
- **WHEN** restart for mlx is asked on another platform
- **THEN** it is refused with no call
Test: tests/test_mlx_dead_912.py::test_restarting_mlx_off_macos_is_refused

### Requirement: node_fallbacks
The watchdog SHALL find node_fallbacks on each serving node that handed back at least `FALLBACK_MAX` (20) requests in the live audit window, and a parked node SHALL yield none.

#### Scenario: At and under the limit
- **WHEN** a node handed back the limit, or one fewer
- **THEN** node_fallbacks trips, or does not
Test: tests/test_watchdog.py::test_node_fallbacks_trip_at_the_limit

#### Scenario: A parked node
- **WHEN** the node is parked
- **THEN** no fallbacks are reported and nothing trips
Test: tests/test_parked_node_1061.py::test_the_watchdog_finds_no_node_fallbacks_for_a_parked_node

### Requirement: stale_mcp
Once the live mcp unit has run at least `ORPHAN_GRACE_S`, the watchdog SHALL find stale_mcp on each other MCP server process on its port, with the command that stops it, the client sessions it still holds (or why they cannot be named) and how they refresh; it SHALL notify and never stop the server itself.

#### Scenario: An old server beside the unit
- **WHEN** an old server runs on the live unit's port
- **THEN** stale_mcp trips on it with the stop command, it is marked orphan, and the action is notify
Test: tests/test_mcp_orphans_1155.py::test_the_watchdog_reports_an_old_server_beside_the_mcp_unit_with_the_command_to_stop_it

#### Scenario: Draining after a restart
- **WHEN** the live unit is younger than the grace
- **THEN** nothing is reported
Test: tests/test_mcp_orphans_1155.py::test_a_server_draining_inside_the_grace_after_a_restart_is_not_reported

#### Scenario: Naming the clients
- **WHEN** lsof lists a client connection to the stale server
- **THEN** the evidence names that client and says how its tool list refreshes
Test: tests/test_stale_mcp_clients_1166.py::test_the_watchdog_names_the_sessions_still_on_a_stale_server_and_how_they_refresh

#### Scenario: No lsof
- **WHEN** lsof cannot be asked
- **THEN** the clients field states the gap
Test: tests/test_stale_mcp_clients_1166.py::test_without_lsof_the_clients_are_a_stated_gap_not_an_empty_list

### Requirement: Notify
Notify SHALL post one macOS desktop notification through osascript with the subject passed as argv, at most once per `NOTIFY_EVERY_S` (3600 s) per criterion, subject and machine counting only notifications shown, and SHALL say why when it fails or the platform has no notifier.

#### Scenario: The notification
- **WHEN** notify is taken on macOS
- **THEN** osascript shows title `SoHoT watchdog`, `<criterion>: <subject>` and the criterion's description, and the outcome starts `notified:`
Test: tests/test_watchdog.py::test_notify_posts_a_desktop_notification_naming_the_criterion_and_target

#### Scenario: Quotes cannot break the script
- **WHEN** the subject holds quotes and AppleScript
- **THEN** it appears only in argv, never in the script
Test: tests/test_watchdog.py::test_notify_passes_the_subject_as_argv_so_quotes_cannot_break_the_script

#### Scenario: Failure or hang
- **WHEN** osascript fails or times out
- **THEN** the outcome starts `notify failed`
Test: tests/test_watchdog.py::test_notify_says_why_when_osascript_fails_or_hangs

#### Scenario: Off macOS
- **WHEN** notify is taken on another platform
- **THEN** the outcome says notify is unavailable on that platform and nothing runs
Test: tests/test_watchdog.py::test_notify_is_unavailable_off_macos_and_says_why

#### Scenario: Held within the interval
- **WHEN** the same criterion and subject trip on wakes inside the interval
- **THEN** one notification is shown, the rest are recorded `notify held`, and after the interval it is shown again
Test: tests/test_watchdog.py::test_a_repeating_notify_is_shown_once_per_criterion_and_target_then_again_after_the_interval

#### Scenario: A failed notify does not hold
- **WHEN** a notify failed and the next trip comes inside the interval
- **THEN** the next one is shown
Test: tests/test_watchdog.py::test_a_failed_notify_does_not_hold_the_next_one

### Requirement: File
File SHALL open a GitHub issue only when `LH_WATCHDOG_FILE` is `1`, SHALL refuse a title or body holding a registered private name, and SHALL not file when an open issue already carries the finding's fingerprint.

#### Scenario: Off by default
- **WHEN** the file switch is not set
- **THEN** the outcome starts `not filed` and gh is never called
Test: tests/test_watchdog.py::test_file_is_off_until_its_own_switch_is_set

#### Scenario: A filed issue
- **WHEN** filing is on and no open issue has the fingerprint
- **THEN** an issue is created whose body carries the fingerprint
Test: tests/test_watchdog.py::test_file_creates_an_issue_carrying_its_fingerprint

#### Scenario: Privacy
- **WHEN** the body would hold a registered name
- **THEN** it is not filed and gh is never called
Test: tests/test_watchdog.py::test_the_watchdog_refuses_to_file_a_body_with_a_registered_name

#### Scenario: Dedupe
- **WHEN** an open issue already holds the fingerprint
- **THEN** the outcome names that issue and nothing is created
Test: tests/test_watchdog.py::test_file_is_deduped_against_an_open_issue_with_the_fingerprint

### Requirement: Pause through the run's own hook
Pause SHALL write the pause file, naming the criterion, inside each running eval's run directory (the subject's own and each child's), SHALL refuse a pause file outside that directory, and SHALL report pause unavailable when the subject has no progress file; the watchdog SHALL read progress files only from running runs under the runs root or an absolute `--out`.

#### Scenario: The pause file
- **WHEN** pause is taken on an eval with a progress file
- **THEN** the pause file exists in its run directory and names the criterion
Test: tests/test_memory_warn_1082.py::test_a_watchdog_pause_names_its_criterion_in_the_pause_file

#### Scenario: Outside the run directory
- **WHEN** the progress file names a pause file elsewhere
- **THEN** pause is refused and nothing is written there
Test: tests/test_watchdog.py::test_pause_refuses_a_pause_file_outside_the_run_directory

#### Scenario: No progress file
- **WHEN** pause is taken on a subject with no progress file
- **THEN** the outcome says pause is unavailable
Test: tests/test_watchdog.py::test_pause_without_a_progress_file_says_it_is_unavailable

#### Scenario: A job pauses each eval under it
- **WHEN** pause is taken on a job whose child eval has a progress file
- **THEN** the child's pause file is written
Test: tests/test_watchdog.py::test_pause_of_a_job_pauses_each_eval_under_it

#### Scenario: The real hook
- **WHEN** a real evals.run progress file is read and paused
- **THEN** the run's next case stops on the pause
Test: tests/test_watchdog.py::test_a_real_evals_run_progress_file_is_read_and_paused_through_its_own_hook

#### Scenario: Only running runs
- **WHEN** run directories hold running, finished and torn progress files
- **THEN** only the running one is read
Test: tests/test_watchdog.py::test_progress_files_are_read_from_run_directories_and_only_while_running

### Requirement: Lane probes each wake
Each wake SHALL send one known-answer completion to every text lane that is resident and not held, record each outcome in `lane_probes`, print one line per lane, and never print all clear while a lane is down; a cold lane or a held machine SHALL get no completion, and a probe that cannot run SHALL be a gap.

#### Scenario: A down lane is not all clear
- **WHEN** one lane answers on the first wake and is dead on the second
- **THEN** every text lane gets a row per wake, the dead lane reads up then down, all clear is printed once, and a `lane extract: down` line is printed
Test: tests/test_lane_probe_924.py::test_the_watchdog_wake_probes_every_text_lane_and_a_down_lane_is_not_all_clear

#### Scenario: A cold model
- **WHEN** the lane's model is not resident
- **THEN** the row is skipped and no completion is sent
Test: tests/test_lane_probe_924.py::test_a_cold_model_gets_no_completion

#### Scenario: A held machine
- **WHEN** this machine's lock is held
- **THEN** the local lane gets no completion
Test: tests/test_lane_probe_924.py::test_a_held_machine_gets_no_completion

#### Scenario: A wrong answer
- **WHEN** the lane answers 200 without the known answer
- **THEN** the lane is down
Test: tests/test_lane_probe_924.py::test_a_200_without_the_known_answer_is_down

#### Scenario: A dead sender
- **WHEN** the probe's own sender dies
- **THEN** the row is skipped, never down
Test: tests/test_lane_probe_924.py::test_a_probe_whose_own_sender_dies_is_skipped_never_down

#### Scenario: No answer
- **WHEN** the server never answers within the lane timeout
- **THEN** the lane is slow and is not asked again while the first request is out
Test: tests/test_lane_probe_924.py::test_a_server_that_never_answers_is_slow_and_is_not_asked_again_while_the_first_is_out

#### Scenario: Refused connection
- **WHEN** the server refuses connections
- **THEN** the lane is down with no completion sent
Test: tests/test_lane_probe_924.py::test_a_server_that_refuses_connections_is_down_without_a_completion

#### Scenario: Probe traffic is tagged
- **WHEN** a probe goes directly to a server
- **THEN** a gateway request row is written with purpose `watchdog`
Test: tests/test_lane_probe_924.py::test_a_direct_probe_is_logged_as_the_gateway_would_with_purpose_watchdog
