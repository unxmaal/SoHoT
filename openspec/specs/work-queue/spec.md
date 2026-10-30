# Work Queue Specification

## Purpose
The shared, durable job queue (`soh jobs`, MCP media tools, planners) and the per-machine worker that runs its jobs when the gate is open, the start time has come and a lock class is free.

## Requirements

### Requirement: Adding a job records it and runs nothing
The queue SHALL store each added job as a pending row in the store's `jobs` table, stamped with the adding machine, and SHALL start nothing at add time.

#### Scenario: A job is added
- **WHEN** a caller adds a command
- **THEN** the queue holds one job in state `pending`
- **AND** the command has not run
Test: tests/test_workqueue.py::test_adding_runs_nothing

#### Scenario: The job is a store row
- **WHEN** a job is added with a title, priority and requester
- **THEN** a `jobs` row holds the argv as JSON, state `pending`, the priority, the requester and a non-null `machine_id`
- **AND** no job file is written under the queue directory
Test: tests/test_workqueue.py::test_a_job_is_a_row_in_the_store

### Requirement: A command that cannot run is refused at add
The queue MUST refuse an empty command, a command whose first word starts with `-`, and a first word that contains whitespace unless it names an existing path.

#### Scenario: A whole command line in one argument or a stray option
- **WHEN** the first argument is a whole command line, or an option the CLI did not recognise
- **THEN** add raises a ValueError naming the reason
- **AND** no job is stored
Test: tests/test_workqueue.py::test_a_command_that_cannot_run_is_refused_when_queued

#### Scenario: A real path with a space
- **WHEN** the first argument contains a space and names an existing file
- **THEN** the job is queued with that argv unchanged
Test: tests/test_workqueue.py::test_a_real_path_with_a_space_is_still_a_command

#### Scenario: An empty command
- **WHEN** add is called with no argv
- **THEN** add raises "a job needs a command"
Test: untested

### Requirement: Evals and adopt commands that would be refused at start are refused at add
The queue MUST refuse an `evals.run` command that the API credit budget refuses, and an `evals.run` repo exam larger than the screen for a candidate with no surviving repo screen, unless the requester is a re-measuring planner (`sweep`, `reverify`). It MUST refuse a `soh adopt` command whose repo challenger is unscreened. A refusal message starts "not queued:".

#### Scenario: A metered gateway eval past the budget
- **WHEN** an `evals.run` job names a metered gateway candidate whose planned spend exceeds the budget
- **THEN** add raises a ValueError naming `api_budget` and stores nothing
- **AND** a local candidate, or the same job under a larger budget, is queued
Test: tests/test_api_spend_1214.py::test_a_queued_eval_of_a_metered_alias_is_refused_past_the_budget_and_a_local_one_is_not

#### Scenario: An unscreened full repo exam
- **WHEN** an `evals.run --modality repo` job names a local candidate with no repo screen result
- **THEN** add raises "not queued: ... no repo screen result"
Test: tests/test_repo_looks_1353.py::test_a_full_repo_exam_for_an_unscreened_candidate_is_refused_at_start_and_at_queue

#### Scenario: A knob sweep or reverify of a measured model
- **WHEN** the same repo exam is added with `requested_by` a re-measuring planner
- **THEN** the job is queued pending
Test: tests/test_repo_looks_1353.py::test_a_knob_sweep_or_reverify_of_a_measured_model_is_queued_without_a_screen

#### Scenario: An unscreened repo adopt through the queue
- **WHEN** a `soh adopt` job names a repo challenger with no repo screen result
- **THEN** add raises "not queued:" with the adopt refusal
Test: untested

### Requirement: A job whose code speaks an older schema is refused at add and failed at start
The queue MUST read `SCHEMA_VERSION` as text from the nearest checkout at or above the job's cwd and refuse the job at add when it is older than the store's schema; a job that has gone stale since its add SHALL be recorded failed at start without running, with the reason in its note and log. A cwd outside any checkout, or a checkout at or ahead of the store, is accepted.

#### Scenario: The code schema is found from a subdirectory
- **WHEN** the cwd is a checkout or a directory inside one
- **THEN** `code_schema` returns that checkout's version, and None outside any checkout
Test: tests/test_jobs_schema_1348.py::test_the_code_schema_is_read_from_the_nearest_checkout

#### Scenario: A stale checkout at add
- **WHEN** a job's cwd is in a checkout two schema versions behind the store
- **THEN** add raises a ValueError naming both versions and the checkout, and nothing is pending
Test: tests/test_jobs_schema_1348.py::test_a_stale_checkout_is_refused_at_add_naming_both_versions

#### Scenario: A current, newer or plain directory
- **WHEN** the cwd's checkout is at or ahead of the store, or the cwd is in no checkout
- **THEN** the job is queued pending
Test: tests/test_jobs_schema_1348.py::test_a_current_or_newer_checkout_and_a_plain_directory_queue

#### Scenario: Stale by the time it starts
- **WHEN** the checkout's schema falls behind the store after the add
- **THEN** run_one records the job `failed` with rc None, does not call the command, and writes the reason to the note and the log
Test: tests/test_jobs_schema_1348.py::test_a_job_gone_stale_since_its_add_fails_at_start_without_running

### Requirement: The CLI runs a job in the deploy checkout unless told otherwise
`soh jobs add` SHALL choose the job's cwd as: an explicit `--cwd` (resolved); else the caller's directory when the machine has no deploy checkout or the caller is inside the deploy; else the deploy when the caller is outside git or at the deploy's commit. It MUST refuse a caller checkout at another commit, naming both commits and `--cwd`.

#### Scenario: A checkout at another commit
- **WHEN** the caller's checkout HEAD differs from the deploy's
- **THEN** `queue_cwd` raises naming both short commits and `--cwd`
Test: tests/test_jobs_cwd.py::test_a_checkout_at_another_commit_is_refused_naming_both

#### Scenario: Same commit
- **WHEN** the caller is a clone at the deploy commit
- **THEN** the job's cwd is the deploy
Test: tests/test_jobs_cwd.py::test_a_checkout_at_the_deploy_commit_runs_in_the_deploy

#### Scenario: Inside the deploy
- **WHEN** the caller is inside the deploy
- **THEN** the job runs where it was asked
Test: tests/test_jobs_cwd.py::test_inside_the_deploy_runs_where_it_was_asked

#### Scenario: Explicit cwd wins
- **WHEN** `--cwd` names a stale checkout
- **THEN** the job's cwd is that checkout
Test: tests/test_jobs_cwd.py::test_the_cli_takes_an_explicit_cwd

#### Scenario: The CLI refuses a stale checkout
- **WHEN** `soh jobs add` runs from a checkout at another commit than the deploy
- **THEN** it exits 1 and stores no job
Test: tests/test_jobs_cwd.py::test_the_cli_refuses_a_stale_checkout

### Requirement: Job ids are store-assigned, distinct and never reused
The queue SHALL take each id from the store's insert, so concurrent adders get distinct ids; a deleted highest id MUST NOT be handed out again; ids SHALL order as numbers and print zero-padded to four digits.

#### Scenario: Two processes add at once
- **WHEN** two processes each add 15 jobs concurrently
- **THEN** all 30 ids are distinct and each job keeps its requester
Test: tests/test_workqueue.py::test_concurrent_adds_from_two_processes_get_distinct_ids

#### Scenario: The highest id is deleted
- **WHEN** the newest job's row is deleted and another is added
- **THEN** the new id is one more than the deleted id
Test: tests/test_workqueue.py::test_a_deleted_highest_id_is_not_handed_out_again

#### Scenario: Ids past four digits
- **WHEN** a job 9999 exists and another is added
- **THEN** the new id is `10000` and pending order is 9999 then 10000
Test: tests/test_workqueue.py::test_ids_are_ordered_as_numbers_not_filenames

### Requirement: Run order is priority, then the order added
The queue SHALL offer ready jobs higher priority first and, within a priority, by id. Only a pending job's priority MAY be changed.

#### Scenario: Insertion order
- **WHEN** three equal-priority jobs are queued and the worker runs
- **THEN** they run in the order added and each is `done`
Test: tests/test_workqueue.py::test_jobs_run_in_the_order_they_were_added

#### Scenario: A higher priority goes first
- **WHEN** jobs a and b at priority 0 and c at priority 5 are queued
- **THEN** they run c, a, b
Test: tests/test_workqueue.py::test_higher_priority_runs_first_and_ties_keep_their_order

#### Scenario: Reprioritising
- **WHEN** a pending job's priority is raised, and later a finished job's priority is set
- **THEN** the raised job moves ahead, and the finished job is refused with "is done"
Test: tests/test_workqueue.py::test_a_pending_job_can_be_reprioritised_and_a_finished_one_cannot

#### Scenario: Priority through the CLI
- **WHEN** `soh jobs priority <id> <n>` is run, or run without the number
- **THEN** the job's priority is n, and the short form exits 1
Test: tests/test_workqueue.py::test_priority_through_the_cli

### Requirement: A job may name its earliest start
The queue SHALL store an optional `not_before`. A start spec SHALL be: empty for none; `night` for `night_start(now)`; `HH:MM` for its next local occurrence at or after now; a local `YYYY-MM-DD HH:MM[:SS]` (or with `T`) for that exact time. A dated start in the past, an out-of-range time and any other text MUST be refused.

#### Scenario: Clock times
- **WHEN** `16:30` and `14:00` are given at 15:00
- **THEN** they mean today 16:30 and tomorrow 14:00, an empty spec is None, and `25:00` is refused
Test: tests/test_workqueue_start_900.py::test_a_clock_time_already_past_today_means_tomorrow

#### Scenario: A dated start
- **WHEN** `2026-10-18 21:00` or `2026-10-18T21:00` is given two days earlier
- **THEN** the start is exactly that local time
Test: tests/test_workqueue_start_900.py::test_a_dated_start_is_that_exact_local_time

#### Scenario: Seconds and the ISO T
- **WHEN** the dated start carries seconds
- **THEN** it is accepted as the same time
Test: tests/test_workqueue_start_900.py::test_a_dated_start_takes_seconds_and_the_iso_t

#### Scenario: A past or invalid date
- **WHEN** a dated start is before now, or month 13
- **THEN** it is refused, the past one naming "past"
Test: tests/test_workqueue_start_900.py::test_a_dated_start_in_the_past_is_refused

#### Scenario: The CLI takes and lists a start
- **WHEN** `soh jobs add --night` and `--not-before 16:45` are run at 15:00, and `--not-before noon`
- **THEN** the jobs show not_before 21:00 and 16:45, `noon` exits non-zero, and the listing says "from 2026-10-16 21:00" and "2 waiting for their start time"
Test: tests/test_workqueue_start_900.py::test_the_cli_takes_night_and_not_before_and_lists_the_start

#### Scenario: An MCP job with a start
- **WHEN** an MCP image is requested with start `night`, and a video with start `later`
- **THEN** the image job's not_before is tonight's night start and its status says it waits for its start time, and the video is refused naming HH:MM
Test: tests/test_workqueue_start_900.py::test_an_mcp_job_with_a_start_says_it_waits_for_it

### Requirement: Night is the discover hours until the watchdog's day start
`night_start(now)` SHALL return now when now is inside a night window, else the next window's start, where a window runs from each installed discover hour outside the watchdog's day hours (the day end hour if none) until the next day start hour. `next_night(now)` SHALL be `night_start(now)` by day and the following night's start at night.

#### Scenario: Night boundaries
- **WHEN** now is 15:00 or 08:00, or 23:00, 03:00 or 07:59
- **THEN** night_start is 21:00 the same day for the first two and now for the rest
Test: tests/test_workqueue_start_900.py::test_night_is_from_the_discover_hour_until_the_day_starts

#### Scenario: The installed discover hours
- **WHEN** the discover hours are 22 and 12 and it is 21:30
- **THEN** night_start is 22:00
Test: tests/test_workqueue_start_900.py::test_night_follows_the_installed_discover_hours

#### Scenario: The next night
- **WHEN** next_night is asked at 15:00, 23:00, 05:00 and 08:00
- **THEN** it is tonight 21:00 by day and tomorrow 21:00 at night
Test: tests/test_confirm_resume_1357.py::test_the_next_night_is_tonight_by_day_and_tomorrow_night_at_night

### Requirement: Night with an explicit start keeps the later of the two
The CLI SHALL turn `--night` with `--not-before WHEN` into `night_start(WHEN)` with no night gate, wherever the options are written; `--night` alone SHALL set the night gate.

#### Scenario: Both options
- **WHEN** `--night --not-before` names a time by day, at night, or a clock time before tonight
- **THEN** not_before is the first night moment at or after that time and `night_gate` is false, before or after the action word
Test: tests/test_workqueue_start_900.py::test_night_with_a_start_keeps_the_later_of_the_two

### Requirement: A job runs only once its start has come
The worker SHALL start only pending jobs that are due, in run order, so a later due job runs while an earlier one waits; the service SHALL not consult the gate while no job is due.

#### Scenario: A night job queued by day
- **WHEN** a night job and an unscheduled job are queued at 15:00
- **THEN** only the unscheduled job runs by day, nothing runs at 20:59, and the night job runs at 21:00
Test: tests/test_workqueue_start_900.py::test_a_night_job_queued_at_15_waits_while_the_gate_is_open_and_runs_at_21

#### Scenario: Nothing due
- **WHEN** the only job is not due
- **THEN** one pass of the service never asks the gate and the job stays pending
Test: tests/test_workqueue_start_900.py::test_the_worker_does_not_wake_for_a_job_that_is_not_due

### Requirement: A day clearance lifts night starts, never clock times
While this machine has a day clearance in force, a pending job with the night gate set SHALL be due whatever its not_before; a job with a clock or dated start MUST still wait for it.

#### Scenario: Clearance given and revoked
- **WHEN** a night-gated job and a 16:45 job are pending at 12:00, then a clearance is given, then revoked
- **THEN** nothing is ready before, only the night job is ready during the clearance, and nothing after the revoke
Test: tests/test_day_clear_1112.py::test_a_clearance_lifts_a_night_start_but_never_a_clock_time

### Requirement: The gate is the pause flag and memory pressure
`gate()` SHALL be closed while the queue's pause flag exists or memory pressure is alarming, and open otherwise, including when pressure is unknown. The worker SHALL check it before each start and MUST NOT stop a running job when it closes.

#### Scenario: Pause and resume
- **WHEN** the queue is paused, then resumed
- **THEN** the gate is closed with "paused (soh jobs resume)", then open
Test: tests/test_workqueue.py::test_pause_closes_the_gate_and_resume_opens_it

#### Scenario: Memory pressure
- **WHEN** pressure is at warn
- **THEN** the gate is closed naming memory pressure, and the service runs nothing
Test: tests/test_workqueue.py::test_the_worker_runs_nothing_under_memory_pressure

#### Scenario: Unknown pressure
- **WHEN** the pressure level cannot be read
- **THEN** the gate is open
Test: tests/test_workqueue.py::test_unknown_pressure_does_not_block

#### Scenario: Calm pressure
- **WHEN** pressure is normal and a job is ready
- **THEN** one service pass runs it to `done`
Test: tests/test_workqueue.py::test_the_worker_runs_the_queue_when_memory_is_calm

#### Scenario: The gate closes mid-queue
- **WHEN** the gate is open for the first start and closed for the second
- **THEN** the first job is done and the second stays pending
Test: tests/test_workqueue.py::test_a_closing_gate_stops_the_next_job_not_the_running_one

### Requirement: Pause and resume through the CLI
`soh jobs pause` and `soh jobs resume` SHALL set and clear the pause flag and report the gate; any further arguments to them are ignored, except that `-h` or `--help` anywhere after any action but `add`, or before `add`'s command, SHALL print the help and change nothing.

#### Scenario: Pause, list, resume
- **WHEN** the operator pauses, adds a job, lists, then resumes
- **THEN** pause reports paused true, the listing shows the job pending with the gate closed, and resume reports paused false
Test: tests/test_workqueue.py::test_pause_resume_and_list_through_the_cli

#### Scenario: A help flag after the action
- **WHEN** `soh jobs pause --help`, `soh jobs resume --help`, `soh jobs add --help` or `soh jobs cancel <id> --help` is run
- **THEN** it prints the help and the pause flag and the queue are unchanged, while `soh jobs add -- echo --help` still queues `echo --help`
Test: tests/test_workqueue.py::test_a_help_flag_after_the_action_prints_help_and_changes_nothing

### Requirement: Quiesce pauses and waits for running work
`quiesce()` SHALL set the pause flag, wait until no runner holds the runner lock, and return whether the queue was already paused, leaving it paused.

#### Scenario: Not paused before
- **WHEN** quiesce runs while a job runs for two more checks
- **THEN** it sleeps twice, returns False and leaves the queue paused
Test: tests/test_workqueue.py::test_quiesce_waits_for_the_running_job_and_reports_it_was_not_paused

#### Scenario: Already paused
- **WHEN** the operator had paused the queue
- **THEN** quiesce returns True and the queue stays paused
Test: tests/test_workqueue.py::test_quiesce_keeps_the_owners_pause

### Requirement: One runner per machine, holding no machine lock
Only the holder of the queue's runner lock SHALL work the queue; a second runner MUST return without running anything. The runner MUST NOT hold the GPU lock around a job; each command takes the locks it needs.

#### Scenario: A second runner
- **WHEN** the runner lock is held and run_pending is called
- **THEN** it returns an empty list and `running()` is true until the lock is released
Test: tests/test_workqueue.py::test_only_one_runner_works_the_queue

#### Scenario: The GPU lock is free inside a job
- **WHEN** a job probes the GPU lock
- **THEN** it can take it, and the held-lock marker is unset in its environment
Test: tests/test_workqueue.py::test_a_job_does_not_hold_the_machine_lock_for_its_whole_run

### Requirement: A worker runs only its own machine's jobs and claims each once
On a shared store, a worker SHALL see pending jobs stamped with its machine or with no machine, and SHALL claim a job in one update guarded by state `pending`, stamping its machine, so a job runs once.

#### Scenario: Another machine's job
- **WHEN** a pending job is stamped with another machine
- **THEN** this worker runs nothing, and runs it once it is stamped with this machine
Test: tests/test_workqueue.py::test_another_machines_job_is_not_run_here

#### Scenario: Two workers, one unowned job
- **WHEN** two machines both see the same unowned pending job and both call run_one
- **THEN** the command runs exactly once
Test: tests/test_shared_store_703.py::test_two_workers_on_one_store_run_an_unowned_job_once

#### Scenario: The claimer is stamped
- **WHEN** another machine claims an unowned job
- **THEN** the job's machine_id is that machine
Test: tests/test_shared_store_703.py::test_a_claimed_job_is_stamped_with_the_machine_that_runs_it

### Requirement: A runner fails its own interrupted jobs at start
When it takes the runner lock, a worker SHALL mark every job this machine claimed that is still `running` as `failed` with note "interrupted; add it again to retry", and MUST leave running jobs of other machines, unowned running jobs, and everything on a machine with no machines row untouched.

#### Scenario: Cut off by a reboot
- **WHEN** this machine's job is left `running` and the worker starts
- **THEN** it is `failed` with "interrupted" in its note and is not rerun
Test: tests/test_workqueue.py::test_a_job_cut_off_mid_run_is_not_silently_rerun

#### Scenario: Another machine's running job
- **WHEN** a job stamped with machine A is running and machine B's worker starts
- **THEN** the job stays `running`
Test: tests/test_shared_store_703.py::test_recover_on_one_machine_leaves_another_machines_stamped_running_job

#### Scenario: An unowned running job
- **WHEN** a running job has no machine and another machine's worker starts
- **THEN** the job stays `running`
Test: tests/test_shared_store_703.py::test_recover_does_not_fail_an_unowned_running_job

#### Scenario: A machine with no row
- **WHEN** recovery runs on a machine with no machines row
- **THEN** nothing is failed
Test: tests/test_shared_store_703.py::test_a_machine_with_no_machines_row_recovers_nothing

### Requirement: Each job has a lock class read from evals.run
The queue SHALL class a job `cloud` when `evals.run.argv_lock_kind` of its argv is a cloud lock kind (every candidate hosted), and `gpu` otherwise, including any non-eval command, `--compare`, an argv that does not parse, or any exception.

#### Scenario: Classes by argv
- **WHEN** jobs are an all-hosted eval (by module or script path), a local or mixed eval, a compare, an unparseable eval, and a non-eval command
- **THEN** the all-hosted ones are `cloud` and the rest `gpu`
Test: tests/test_worker_cloud_1153.py::test_a_job_needs_the_lock_evals_run_would_take

#### Scenario: One rule, no copy
- **WHEN** `evals.run.lock_kind` is replaced to answer cloud
- **THEN** a local eval job is classed `cloud`
Test: tests/test_worker_cloud_1153.py::test_the_class_is_read_from_evals_run_lock_kind_not_a_copy

### Requirement: One GPU job at a time, cloud jobs beside it in free slots
The worker SHALL run at most one `gpu` job and up to the cloud slot count of `cloud` jobs at once, where a slot held outside the queue counts as taken; it SHALL start the first ready job in run order whose class is free and look for another every few seconds while jobs run. A job that raises in the worker SHALL stop new starts and be raised after the jobs beside it finish.

#### Scenario: A cloud job beside a GPU job
- **WHEN** a GPU job runs and a second GPU job and a cloud job are queued
- **THEN** the cloud job runs to done while the GPU job runs, and the second GPU job waits until the first ends
Test: tests/test_worker_cloud_1153.py::test_with_a_gpu_job_running_a_cloud_job_starts_and_a_gpu_job_does_not

#### Scenario: Slots fill in priority order
- **WHEN** one cloud slot exists and a low and a high priority cloud job are queued behind a GPU job
- **THEN** the high one starts beside the GPU job and the low one waits for the slot
Test: tests/test_worker_cloud_1153.py::test_cloud_jobs_fill_the_free_slots_in_priority_order

#### Scenario: A slot held outside the queue
- **WHEN** the only cloud slot is held by another process
- **THEN** the cloud job stays pending, the worker returns, and the job runs once the slot is free
Test: tests/test_worker_cloud_1153.py::test_a_cloud_slot_held_outside_the_queue_keeps_a_cloud_job_waiting

#### Scenario: A worker error
- **WHEN** starting a cloud job raises while a GPU job runs
- **THEN** run_pending raises it after the GPU job ends, and nothing else starts
Test: tests/test_worker_cloud_1153.py::test_a_job_that_breaks_the_worker_is_raised_after_the_jobs_beside_it_finish

#### Scenario: The current job is the GPU one
- **WHEN** a GPU job and a newer cloud job both run
- **THEN** `current()` is the GPU job
Test: tests/test_worker_cloud_1153.py::test_current_is_the_gpu_job_and_the_probe_spares_every_running_jobs_models

### Requirement: A job's exit code sets its final state
run_one SHALL record rc 0 as `done`, the evals pause code (75) as `paused`, and any other rc as `failed`; a command that cannot be started SHALL be recorded with rc 127 and "could not start" in its log; a job whose cancel flag is set when it exits SHALL be `cancelled`. `paused` is final for the queue: nothing requeues it.

#### Scenario: 75, 1 and 0
- **WHEN** three jobs exit 75, 1 and 0
- **THEN** they are `paused`, `failed` and `done`, and the listing shows the first as paused
Test: tests/test_confirm_resume_1357.py::test_the_queue_records_exit_75_as_paused_and_lists_it

#### Scenario: A failure does not stop the queue
- **WHEN** a job exits 3 after printing, then another job is queued behind it
- **THEN** the first is `failed` rc 3 with its output in the log and the second is `done`
Test: tests/test_workqueue.py::test_a_failed_job_is_recorded_and_the_rest_still_run

#### Scenario: A paused job's continuation
- **WHEN** a queued confirmation pauses and its command queues a continuation, which the next job runs
- **THEN** the first job is `paused` with rc 75 and the continuation is `done`
Test: tests/test_confirm_resume_1357.py::test_a_paused_confirmation_is_paused_queues_its_continuation_and_the_next_job_resumes_it

#### Scenario: A command that cannot be started
- **WHEN** the job's executable does not exist
- **THEN** the job is `failed` with rc 127 and "could not start" in its log
Test: untested

### Requirement: A job runs as its own process group and leaves nothing behind
run_one SHALL start each job as the leader of a new process group with stderr merged into the job log, record its pid where cancel finds it, and after the leader exits stop whatever of its group is still running, noting it in the log.

#### Scenario: A child left holding a lock
- **WHEN** a job starts a grandchild holding a lock and exits
- **THEN** the lock is free afterwards, the job is `done`, and the log says it stopped processes the job left running
Test: tests/test_stop_group_677.py::test_a_job_that_leaves_a_child_holding_the_lock_does_not_keep_it

### Requirement: Stopping a process group terminates, waits, then kills
`stop_group(pid)` SHALL return `gone` if no member can take a signal, else send SIGTERM to the group, wait up to the grace, and return `term` if it emptied or SIGKILL it and return `kill`. A group of only zombies, or one whose kill raises EPERM with every member a zombie, SHALL count as stopped; a member still inside exit counts as alive.

#### Scenario: An unreaped leader
- **WHEN** the leader has exited unreaped and a grandchild lives
- **THEN** stop_group stops the group without raising
Test: tests/test_stop_group_677.py::test_a_group_whose_leader_exited_unreaped_is_stopped_without_raising

#### Scenario: The caller's own leader
- **WHEN** the caller passes its own Popen
- **THEN** the leader is reaped while the group stops
Test: tests/test_stop_group_677.py::test_the_caller_s_own_leader_is_reaped_while_its_group_stops

#### Scenario: A member that ignores TERM
- **WHEN** a grandchild ignores SIGTERM
- **THEN** it is killed after the grace
Test: tests/test_stop_group_677.py::test_a_grandchild_that_ignores_term_is_killed_after_the_grace

#### Scenario: Linux zombies
- **WHEN** every member of the group is a zombie in /proc
- **THEN** the group reads as stopped
Test: tests/test_stop_group_677.py::test_linux_reads_a_group_of_zombies_as_stopped

#### Scenario: macOS member inside exit
- **WHEN** a member is not yet a zombie
- **THEN** the group reads as alive
Test: tests/test_stop_group_677.py::test_macos_reads_a_member_inside_exit_as_alive

### Requirement: Cancel records a pending job cancelled and stops a running one
`soh jobs cancel <id>` SHALL keep a pending job's row and record it `cancelled` with a finish time and a note, so it never starts and every reader of its state sees `cancelled`; for a running job with a live process on this machine it SHALL set the cancel flag, stop the job's process group with the grace, and record the job `cancelled` with a note saying how it stopped. It MUST refuse a running job with no process here, and any job that is neither pending nor running.

#### Scenario: Cancel a pending job
- **WHEN** a pending job is cancelled and the worker runs
- **THEN** the job is `cancelled` with a finish time, no start and a note, it never runs, and a second cancel is refused naming its state
Test: tests/test_workqueue.py::test_a_cancelled_pending_job_is_kept_and_recorded_cancelled_and_never_runs

#### Scenario: Cancel a running job and its children
- **WHEN** a running job with a grandchild is cancelled with a short grace
- **THEN** the job is `cancelled` with a note and a finish time, the leader and grandchild are gone, and the worker thread ends
Test: tests/test_workqueue.py::test_cancel_stops_a_running_job_and_its_children_and_records_it

#### Scenario: A finished job
- **WHEN** a done job is cancelled
- **THEN** cancel raises naming its state
Test: tests/test_workqueue.py::test_cancel_refuses_a_finished_job

#### Scenario: Running elsewhere
- **WHEN** a job is `running` with no live pid on this machine
- **THEN** cancel raises "no process"
Test: tests/test_workqueue.py::test_cancel_refuses_a_running_job_with_no_process_on_this_machine

### Requirement: A job's environment names it so its runs link back
run_one SHALL set `LH_JOB_ID` to the job id in the command's environment, and a run stored under that variable SHALL be linked to the job; a run stored with no or an unknown job id SHALL link to none.

#### Scenario: An eval run inside a job
- **WHEN** a job stores a run
- **THEN** the job lists that run id and a plain job lists none
Test: tests/test_workqueue.py::test_a_job_that_ran_evals_links_to_its_run

#### Scenario: A run outside any job
- **WHEN** a run is stored with no job id, or an id with no job
- **THEN** link_run returns false and the run's job_id stays null
Test: tests/test_workqueue.py::test_a_run_stored_outside_any_job_links_to_none

### Requirement: Durations come from this machine's finished jobs
`durations(title)` SHALL return the seconds of each `done` job with that title stamped with this machine, excluding unstamped jobs, or every machine's when asked for anywhere.

#### Scenario: Another machine's runs
- **WHEN** this machine and another both finished a job of the title
- **THEN** only this machine's duration is returned
Test: tests/test_machine_host.py::test_durations_are_this_machines_only

#### Scenario: Unstamped jobs
- **WHEN** one of two finished jobs has no machine
- **THEN** only the stamped one is counted
Test: tests/test_machine_host.py::test_jobs_with_no_machine_are_not_counted_as_this_ones

### Requirement: The listing shows every job, its start and the lock it holds
`soh jobs list` SHALL print running jobs, then pending ones in run order with any start not yet due, then done, paused, failed and cancelled jobs; it SHALL name the lock each running job holds and every lock held by no running job.

#### Scenario: A cancelled job is listed
- **WHEN** a job is recorded cancelled
- **THEN** the listing shows it as cancelled
Test: tests/test_workqueue.py::test_the_listing_shows_a_cancelled_job

#### Scenario: Locks by job
- **WHEN** a running job holds a cloud slot and a GPU holder names a job that is not running
- **THEN** the running job is shown holding the cloud lock and the GPU holder is listed as outside the queue
Test: tests/test_cloud_lock_1135.py::test_soh_jobs_names_the_lock_a_running_job_holds

#### Scenario: The CLI keeps the command's own options
- **WHEN** `soh jobs add --title T --json -- echo --title x -- y` is run
- **THEN** the title is T and the argv is `echo --title x -- y`
Test: tests/test_workqueue.py::test_the_command_keeps_its_own_separators_and_flags

### Requirement: Old job files are imported once
At migration the queue SHALL import each readable pre-store job file into a row with its id, fields and requester `migration`, link runs named in its log, skip unreadable files and ids already present, and leave the files in place.

#### Scenario: Import and re-import
- **WHEN** three old job files and one bad file are present at migration, and import runs again later
- **THEN** three jobs exist with their fields and run link, the next id follows the highest, and the second import adds nothing
Test: tests/test_workqueue.py::test_the_migration_imports_old_job_files_once_and_links_their_runs
