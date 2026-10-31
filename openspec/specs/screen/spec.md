# Screen Specification

## Purpose
The rungs between a proposal and a measurement: inspect reads a candidate's card or source before any weights are fetched, the rank orders the queue by what a screen would teach, and the screen runs the cheapest real thing on what arrived and records whether it ran at all, with a verdict that names what would reopen it.

## Requirements

### Requirement: Nothing is fetched before the gate
The inspect tier SHALL decide each proposal from a model card or a shallow source clone alone, read as text, and MUST NOT download weights, install anything or import cloned code before it writes a verdict.

#### Scenario: a model card is read with nothing cloned
- **WHEN** `inspect_model()` is given a registry card for a model that fits
- **THEN** the verdict is fits, the Fit names the registry it read and the size, lane and runtime come from that one card
Test: tests/test_harness_registry.py::test_a_model_card_yields_a_verdict_with_nothing_cloned

#### Scenario: the source clone is shallow
- **WHEN** `inspect()` clones a candidate's source tree
- **THEN** the clone asks for one commit of one branch with no tags
Test: tests/test_harness_inspect.py::test_the_clone_is_shallow_and_single_branch

#### Scenario: a half clone is redone, not read
- **WHEN** the clone directory holds a `.git` and no worktree, as a killed clone leaves it
- **THEN** `clone()` removes it and clones again, so an empty tree is never read as a repo with no weights and no runtime
Test: tests/test_harness_inspect.py::test_a_half_clone_is_removed_rather_than_scanned

### Requirement: One verdict per proposal, in a fixed order
`decide()` SHALL return exactly one verdict from `verdicts()`, judged in this order: a runtime the machine refuses, a ds4 file, a weight format no runner of the lane loads, the size against the ceiling, upstream idleness, a missing entry point, unsized weights, and otherwise fits. The needs-* verdicts MUST be derived from the machine's runtime probes, never written by hand.

#### Scenario: a declared runtime outranks size
- **WHEN** a source tree declares a CUDA dependency, is small, and the machine has no CUDA
- **THEN** the verdict is needs-cuda, not a size answer
Test: tests/test_harness_inspect.py::test_a_declared_cuda_dependency_outranks_everything

#### Scenario: the verdict list is derived
- **WHEN** `verdicts()` is read
- **THEN** it holds fits and a needs-* entry for every runtime the machine probes, including ones added after the list was first written
Test: tests/test_harness_inspect.py::test_the_verdict_list_is_derived_rather_than_written_down

### Requirement: Runtime refusals name the runtime, not the platform
The gate SHALL count a runtime as required only when the repo offers it (an mlx import, a CUDA marker in a declared runtime dependency, GGUF weights, a ds4 file) and SHALL refuse the repo only when the machine refuses every runtime it offers; the refusal's until MUST list every offered runtime.

#### Scenario: a CUDA mention in code is not a dependency
- **WHEN** a CUDA marker appears in code but in no dependency file
- **THEN** `scan()` records it as mentioned and not as required
Test: tests/test_harness_inspect.py::test_cuda_in_code_is_recorded_but_not_as_a_dependency

#### Scenario: no offered runtime present names them all
- **WHEN** a repo offers mlx and CUDA on a machine with neither
- **THEN** the verdict is a needs-* and its reason names both runtimes
Test: tests/test_harness_inspect.py::test_a_repo_offering_two_runtimes_on_a_machine_with_neither_names_both

#### Scenario: GGUF weights need llama.cpp
- **WHEN** a GGUF repo is judged on a machine without llama.cpp
- **THEN** the verdict is needs-llamacpp, and the same repo is not refused where llama.cpp exists
Test: tests/test_harness_gguf_runtime.py::test_a_gguf_is_refused_by_name_on_a_machine_without_llamacpp

#### Scenario: the refusal waits on the runtime it lacks
- **WHEN** a ds4 repo is judged on a machine with llama.cpp and no ds4
- **THEN** the verdict is needs-ds4 and `until_of()` is `runtime:ds4`
Test: tests/test_ds4.py::test_a_ds4_repo_on_a_machine_without_ds4_waits_for_ds4_not_llama

### Requirement: The memory ceiling belongs to the machine asking
`ceiling_bytes()` SHALL return a discrete card's VRAM, and for unified memory SHALL scale `MEMORY_CEILING` by the machine's RAM over `MEMORY_CEILING_RAM_GB`, falling back to `MEMORY_CEILING` when the RAM is unknown.

#### Scenario: the measured machine keeps its ceiling
- **WHEN** the unified RAM equals `MEMORY_CEILING_RAM_GB`
- **THEN** the ceiling is `MEMORY_CEILING`
Test: tests/test_inspect_ceiling.py::test_the_machine_it_was_measured_on_keeps_its_ceiling

#### Scenario: a larger unified machine gets a larger ceiling
- **WHEN** the unified RAM is a multiple of `MEMORY_CEILING_RAM_GB`
- **THEN** the ceiling is `MEMORY_CEILING` scaled by the same multiple
Test: tests/test_inspect_ceiling.py::test_a_96_gb_mac_is_not_held_to_the_minis_ceiling

#### Scenario: a discrete card is held to its VRAM
- **WHEN** the accelerator is a discrete card
- **THEN** the ceiling is its VRAM, and one weight can be too-big for a small card and fit a larger one
Test: tests/test_harness_inspect.py::test_a_weight_over_the_cards_vram_is_too_big_for_that_card

### Requirement: A listing is sized by the variant this machine would run
`size_listing()` SHALL size a registry listing by the smallest variant the lane's runner opens and the machine can run, under the ceiling in use; the inspect verdict, `hf_facts()` and `card_description()` MUST report that one size.

#### Scenario: a multi-quant listing is sized at a quant, not the repo total
- **WHEN** a listing holds several quantised files whose sum is far over the ceiling and one quant fits
- **THEN** the verdict is fits with that quant's size, and under a ceiling no quant fits it is too-big with `ceiling_gb:>` the smallest quant
Test: tests/test_too_big_reopen_880.py::test_a_multi_quant_listing_is_sized_at_its_smallest_quant_not_the_repo_total

#### Scenario: one size everywhere
- **WHEN** a mixed mlx and GGUF listing is read by `inspect_model()`, `hf_facts()` and the description
- **THEN** all three report the same smallest variant
Test: tests/test_listing_size_964.py::test_a_mixed_mlx_and_gguf_listing_has_one_size_everywhere

#### Scenario: a too-big verdict names its variant
- **WHEN** the only variant of a listing exceeds the ceiling
- **THEN** the verdict is too-big, the reason names the variant's files, and the until is `ceiling_gb:>` its size
Test: tests/test_variants_947.py::test_a_single_variant_transformers_listing_is_still_too_big_and_names_its_variant

### Requirement: An unknown size is never zero and never too-big
The gate SHALL keep an unsized weight apart from a small one, and MUST NOT return too-big when the floor is not known: more weights unsized than sized, an unsized weight the registry rate-limited, or weights no variant groups each make the verdict unknown instead.

#### Scenario: an unreachable registry sizes nothing
- **WHEN** the registry call fails
- **THEN** `hf_size()` returns the unknown marker, never zero, and nothing is cached
Test: tests/test_harness_inspect.py::test_an_unreachable_registry_sizes_nothing_rather_than_zero

#### Scenario: a truncated size scan cannot claim too-big
- **WHEN** the one sized weight is over the ceiling and many more were never sized
- **THEN** the verdict is unknown and the reason says the rest were never sized
Test: tests/test_harness_inspect.py::test_too_big_is_not_claimed_from_a_truncated_size_scan

#### Scenario: a rate-limited small weight cannot make the repo too-big
- **WHEN** the small weights a repo names were rate-limited and only large ones were sized
- **THEN** the verdict is unknown and the reason names the rate limit
Test: tests/test_fetch_retention_704.py::test_a_429_on_the_small_variants_only_is_unknown_not_too_big

#### Scenario: weights no variant groups are our gap
- **WHEN** a listing's weights sum over the ceiling but no variant groups them
- **THEN** the verdict is unknown with reason harness and until `layout:` naming where the weights sit, and the same layout under the ceiling fits
Test: tests/test_variants_947.py::test_weights_no_variant_groups_are_queued_as_our_gap_never_too_big_on_the_sum

### Requirement: A weight format no runner loads is a format gap
When a listing holds weights only in formats no runner of its lane loads, the gate SHALL return unknown with reason harness and an until naming those formats, never a verdict about the candidate.

#### Scenario: a listing in a foreign format
- **WHEN** a lane's listing holds only formats its runners cannot open
- **THEN** the verdict is unknown, `reason_of()` is harness, `until_of()` is `format:` plus the formats, and the reason starts "runners wanted"
Test: tests/test_fetch_files_1040.py::test_a_listing_in_no_format_its_lane_loads_is_a_format_gap_at_inspect

#### Scenario: the writer queues the format gap
- **WHEN** the inspect step records such a proposal
- **THEN** its state verdict is queued with reason harness and the `format:` until, and the fetch tier waits on it
Test: tests/test_fetch_files_1040.py::test_the_format_gap_is_queued_and_fetch_waits_on_it

### Requirement: The inspect writer settles only what it knows
The inspect step SHALL write fits as queued, an unknown with an ungrouped layout or format gap as queued, and every other verdict except unknown as declined, each carrying `reason_of()`, `until_of()` and the ceiling it was judged against; an unknown with no layout MUST settle nothing.

#### Scenario: too-big records its ceiling
- **WHEN** inspect declines a listing as too-big
- **THEN** the verdict is declined with the ceiling it was judged against and until `ceiling_gb:>` the smallest size
Test: tests/test_too_big_reopen_880.py::test_the_inspect_writer_records_the_ceiling_it_judged_against

#### Scenario: an ungrouped layout is queued for us
- **WHEN** inspect records a listing whose weights no variant groups
- **THEN** the state verdict is queued, reason harness, until `layout:`
Test: tests/test_variants_947.py::test_the_inspect_writer_queues_an_ungrouped_layout_with_reason_harness

#### Scenario: an unknown from missing sizes writes nothing
- **WHEN** every weight a repo names was unsized and no layout or format gap was found
- **THEN** no inspect verdict is written and the proposal keeps its state for the next sweep
Test: untested

### Requirement: Registry answers are kept apart
`hf_model()` SHALL raise `Gone` only for a registry not-found answer, `Deferred` for a persisting rate limit, and `InspectError` for anything else including a gated model; a `Gone` name SHALL be declined with reason upstream until any later commit, and a `Deferred` one MUST stop the batch and leave the rest queued.

#### Scenario: a not-found and an outage differ
- **WHEN** the registry answers not-found, and separately times out
- **THEN** the first raises `Gone` and the second an `InspectError` that is not `Gone`
Test: tests/test_harness_registry.py::test_a_404_and_an_outage_are_different_answers

#### Scenario: a gated model is not missing
- **WHEN** the registry answers unauthorised
- **THEN** `hf_model()` raises an `InspectError` that is not `Gone`
Test: tests/test_harness_registry.py::test_a_gated_model_is_not_reported_as_missing

#### Scenario: a gone name waits on a new commit
- **WHEN** neither registry has a name
- **THEN** it is declined with reason upstream and an until `commit_after:` the time of asking, which a later commit meets
Test: tests/test_coherence_991.py::test_a_gone_name_is_declined_upstream_until_it_commits_again

#### Scenario: a persisting rate limit stops the batch
- **WHEN** the registry keeps answering rate-limited
- **THEN** one name is asked `SIZE_RETRIES` plus one times, no verdict is written, and the rest are left queued for the next sweep
Test: tests/test_inspect_ratelimit.py::test_a_persisting_429_stops_the_batch_and_leaves_the_rest_queued

### Requirement: A source tree is judged as a program
For a source tree the gate SHALL size weights only from the shallow clone's own weight files, refuse a tree whose weight files exceed `CLONE_KB_CAP` as `WEIGHTS_IN_GIT` with reason candidate and no until, decide by the smallest named weight, size at most `SIZE_LIMIT` weights, refuse a tree with no entry point, and refuse one whose upstream is idle past the dead-days threshold.

#### Scenario: weights in git are refused from the clone
- **WHEN** a shallow clone holds weight files over the cap
- **THEN** the verdict is `WEIGHTS_IN_GIT`, `reason_of()` is candidate and `until_of()` is empty
Test: tests/test_harness_inspect.py::test_a_repo_carrying_weights_in_git_is_refused_from_its_shallow_clone

#### Scenario: a long history is not weights
- **WHEN** a repo's registry size is large from history but its clone holds no weight files
- **THEN** it is cloned and read, and is neither too-big nor `WEIGHTS_IN_GIT`
Test: tests/test_coherence_991.py::test_a_long_history_with_no_weights_in_the_tree_is_cloned_and_read

#### Scenario: the smallest named weight decides
- **WHEN** a tree names one small weight and one far over the ceiling
- **THEN** the verdict is fits
Test: tests/test_harness_inspect.py::test_the_smallest_weight_decides_not_the_largest

#### Scenario: sizing is bounded
- **WHEN** a tree names many more weights than `SIZE_LIMIT`
- **THEN** at most `SIZE_LIMIT` are asked about and the rest are recorded unsized
Test: tests/test_harness_inspect.py::test_only_a_bounded_number_of_weights_is_sized

#### Scenario: no entry point applies to source trees only
- **WHEN** a source tree has nothing to call
- **THEN** the verdict is no-entry-point, while a model card with no entry point is not refused for it
Test: tests/test_harness_registry.py::test_a_source_tree_with_no_entry_point_is_still_refused

#### Scenario: an idle upstream is dead
- **WHEN** the last commit is older than the dead-days threshold passed to `inspect()`
- **THEN** the verdict is dead, and a lenient threshold passed the same way does not refuse it
Test: tests/test_harness_inspect.py::test_inspect_passes_dead_days_through_to_decide

### Requirement: ds4 files are held against resident weights
A repo whose files ds4 recognises SHALL be held against its resident weights rather than the file size, SHALL fit over the ceiling when ds4 streams it from disk, and SHALL be unknown when ds4 lists none of its files.

#### Scenario: resident weights decide
- **WHEN** a ds4 file's resident weights fit and the whole file does not
- **THEN** the verdict is fits, the reason names the resident and on-disk sizes, and the download size is still the whole file
Test: tests/test_ds4.py::test_a_ds4_repo_is_sized_by_its_resident_weights_not_its_file

#### Scenario: resident weights over the ceiling
- **WHEN** the resident weights exceed the ceiling and ds4 cannot stream the model
- **THEN** the verdict is too-big with until `ceiling_gb:>` the resident size
Test: tests/test_ds4.py::test_the_ceiling_is_held_against_resident_weights

#### Scenario: an unlisted ds4 file is unknown
- **WHEN** a ds4 repo's file is not one ds4 lists
- **THEN** the verdict is unknown
Test: tests/test_ds4.py::test_a_file_ds4_does_not_list_is_unknown_rather_than_guessed

### Requirement: Card facts are columns, read once
`card_facts()` SHALL read a card's task, library, tags, lineage, attachment kind, runtime need, model type and remote-code evidence into fields once, at inspect; `runtime_needed()` SHALL name a runtime only from a CUDA-only kernel or format word or a serving library, and MUST let a loadable variant in the listing outrank the library tag. `attaches_to` SHALL be set only when a whole tag, the name or the listing says the repo attaches to a model, and a listing that holds a full model MUST outweigh a weight word on its card.

#### Scenario: a card naming a foreign runtime is read
- **WHEN** a card is tagged with a CUDA-only format, or names a serving library as its library
- **THEN** `runtime_needed` is that runtime
Test: tests/test_harness_runtime_needed.py::test_a_card_that_names_its_runtime_is_read

#### Scenario: quantisation formats are not refused
- **WHEN** a card is tagged awq or gptq
- **THEN** `runtime_needed()` is empty
Test: tests/test_harness_runtime_needed.py::test_awq_and_gptq_are_deliberately_not_refused

#### Scenario: a serving-library tag beside a loadable copy is not a refusal
- **WHEN** a card names a serving library and its listing also holds a variant another runner loads
- **THEN** `runtime_needed` is empty and the fetch tier does not call it unrunnable
Test: tests/test_variants_947.py::test_a_vllm_tag_beside_a_loadable_copy_is_a_fact_on_the_card_not_a_refusal

#### Scenario: a real adapter is one
- **WHEN** a card's listing is an adapter or control model
- **THEN** `attaches_to` names its kind
Test: tests/test_attachment_tags_949.py::test_a_real_adapter_is_still_one_by_its_listing

#### Scenario: a full listing is a model
- **WHEN** a card carries a weight word in a tag but its listing is a full model
- **THEN** `attaches_to` is empty
Test: tests/test_attachment_tags_949.py::test_a_full_listing_outweighs_a_weight_word

### Requirement: A vision card the text runner cannot build is a vision candidate
The gate SHALL route an image-text-to-text card to the vision lane exactly when the text runner's gap for it would be `runner:` `VLM_RUNNER`: a typed, non-GGUF card whose model type the pinned mlx-lm does not build, with no OCR or lane-naming tag.

#### Scenario: an untagged vision card lands in vision
- **WHEN** an image-text-to-text card's model type is not one mlx-lm builds
- **THEN** `lane_and_source()` is vision from the card
Test: tests/test_vision_engines_1282.py::test_an_image_text_to_text_card_with_no_ocr_tag_lands_in_vision

#### Scenario: vision routing and the text gap agree
- **WHEN** `vision_card()` and `text_gap()` read the same card
- **THEN** vision routing holds exactly when the text gap waits on `VLM_RUNNER`
Test: tests/test_vision_engines_1282.py::test_the_vision_route_is_the_same_question_as_the_text_gap

### Requirement: Remote code is a gap only for a type the pinned transformers lacks
`code_evidence()` SHALL record remote-code evidence only when config.json carries an auto_map, naming the modeling or configuration files anywhere in its listing whatever modules the auto_map names; `remote_code.gap()` SHALL report a gap only when that evidence exists and the model type is absent from the committed transformers snapshot, whose pin MUST match the one the hf-task venv installs.

#### Scenario: the evidence is the auto_map and the code files in the listing
- **WHEN** config.json has no auto_map, has one with code files listed, or has one with none
- **THEN** the evidence is empty, the sorted code file names, or the word auto_map
Test: tests/test_remote_code.py::test_the_evidence_is_the_auto_map_and_the_code_files_in_the_listing

#### Scenario: only a type transformers lacks is a gap
- **WHEN** the evidence names code for a model type the snapshot ships, and separately for one it does not
- **THEN** the first is no gap and the second names the code, the type and the pin
Test: tests/test_remote_code.py::test_only_code_for_a_model_type_transformers_lacks_is_a_gap

#### Scenario: the snapshot is the pinned transformers
- **WHEN** the snapshot header is compared with `TRANSFORMERS_PIN` in scripts/versions.sh
- **THEN** they match
Test: tests/test_remote_code.py::test_the_snapshot_is_of_the_transformers_the_hf_task_venv_pins

#### Scenario: an older card stands in with its custom_code tag
- **WHEN** a card has no stored model type, so inspect never read its auto_map, is tagged custom_code, and the loader's error names a type transformers does not ship
- **THEN** a runtime decline of it waits on `policy:trust_remote_code@` that type
Test: tests/test_runner_gap_until_950.py::test_an_audited_runtime_decline_waits_on_its_cause_not_a_release

#### Scenario: a later card is not refused on its custom_code tag
- **WHEN** a card has a stored model type transformers does not ship, no auto_map evidence, and the custom_code tag
- **THEN** `pre_screen()` passes it, a runtime decline of it does not wait on `policy:`, and the same card with no stored type still falls back on the tag
Test: tests/test_runner_gap_until_950.py::test_a_card_read_after_the_remote_code_column_is_not_refused_on_its_custom_code_tag

### Requirement: The pre-screen card gate refuses before download
`engines.card_gap()` SHALL refuse, before any download, an MLX conversion or a remote-code gap for any `HF_TASK_ENGINES` engine, and SHALL ask `runner_gaps.pre_screen()` for the bare text spec and the `CARD_CHECKED` engines; `pre_screen()` MUST refuse a library outside `TEXT_LIBRARIES`, a vision task the text runner cannot build, a remote-code gap, a type in `DECLINED`, a tag in `VENDOR_FORMATS`, and for a diffusers engine a foreign library, a pipeline class the pinned diffusers lacks, or a listing with no model_index.json.

#### Scenario: a card the runner cannot load is refused
- **WHEN** a card names a vision task the text runner cannot build, remote code, a foreign library, a vendor format, a declined type, a pipeline class the pin lacks, or no model_index.json
- **THEN** `card_gap()` starts "needs its own runner: "
Test: tests/test_runner_gap_until_950.py::test_a_card_the_runner_cannot_load_is_refused_before_download

#### Scenario: a card the runner loads passes
- **WHEN** a card is a text model mlx-lm builds, a vision card whose text part mlx-lm builds, an untyped card, a GGUF, or a stock diffusers pipeline
- **THEN** `card_gap()` is empty
Test: tests/test_runner_gap_until_950.py::test_a_card_the_runner_loads_passes_the_gate

#### Scenario: an MLX conversion is a gap for every hf-task engine
- **WHEN** a card tagged mlx is spelled for any `HF_TASK_ENGINES` engine
- **THEN** `card_gap()` refuses it and names mlx
Test: tests/test_new_lane_loop_faults.py::test_an_mlx_conversion_is_a_runner_gap_for_every_hf_task_engine

#### Scenario: the runner snapshots are the pinned runtimes
- **WHEN** the mlx-lm and diffusers snapshot headers are compared with uv.lock and `DIFFUSERS_PIN`
- **THEN** they match
Test: tests/test_runner_gap_until_950.py::test_the_snapshots_are_of_the_pinned_runtimes

### Requirement: A runner gap is held at fetch and reported to a person
The fetch tier SHALL check each queued proposal's runner gap before downloading and, on a gap, SHALL record it queued with reason harness and the gap's text instead of downloading or declining it; `rank.runnerless()` SHALL list every such candidate with why.

#### Scenario: remote code is held before any download
- **WHEN** a queued OCR candidate needs remote code
- **THEN** nothing is downloaded, the fetch result names the code it ships, and the proposal stays queued
Test: tests/test_remote_code.py::test_the_fetch_tier_queues_it_before_any_download

#### Scenario: a full model no lane runs is queued as harness
- **WHEN** a full model whose lane has no runner for it reaches fetch
- **THEN** nothing is downloaded and its latest verdict is queued with reason harness
Test: tests/test_attachment_tags_949.py::test_a_full_model_no_lane_runs_is_queued_as_a_runner_gap

#### Scenario: runners wanted lists only the gaps
- **WHEN** remote-code candidates and a native one are ranked for runners wanted
- **THEN** only the remote-code ones are listed
Test: tests/test_remote_code.py::test_runners_wanted_lists_them_and_not_the_native_one

### Requirement: A runtime decline waits on what its cause lacks
`runner_gaps.cause_until()` SHALL give a load-failed screen decline an until naming the missing runner, format, policy or package (`runner:`, `format:`, `policy:trust_remote_code`, `package:`), and SHALL return empty only where a newer release of the failing runtime could change the outcome; each key MUST be met only once the lack is filled.

#### Scenario: an audited decline waits on its cause
- **WHEN** a load failure is a vision type, a type transformers ships but mlx-lm does not, remote code, or tensors the runner does not read
- **THEN** the until is `runner:` `VLM_RUNNER`, `runner:` `TEXT_RUNNER`, `policy:trust_remote_code`, or `format:` the odd tensor leaf, never `version:`
Test: tests/test_runner_gap_until_950.py::test_an_audited_runtime_decline_waits_on_its_cause_not_a_release

#### Scenario: a type no runtime ships still waits on a release
- **WHEN** a text model type no snapshot ships fails to load
- **THEN** the until stays `version:` the text runtime
Test: tests/test_runner_gap_until_950.py::test_a_text_architecture_mlx_lm_could_add_still_waits_on_its_release

#### Scenario: an engine layout gap names the engine and what it could not assemble
- **WHEN** a diffusers screen fails for want of model_index.json
- **THEN** the verdict is declined with failure class load-failed-layout and until `runner:diffusers/single-file`
Test: tests/test_runner_gap_until_950.py::test_a_screen_verdict_records_its_failure_class

#### Scenario: the until keys open only when the lack is filled
- **WHEN** `until_met()` reads `runner:` and `policy:` untils
- **THEN** a runner until opens once that engine is registered, and a policy until opens once its type is native, and not before
Test: tests/test_runner_gap_until_950.py::test_the_until_keys_have_readers_that_open_only_when_the_lack_is_filled

### Requirement: A missing package waits on the venv its runner imports from
`package_until()` SHALL name the missing distribution and the venv `venv_of()` gives the candidate's runner (a process engine's venv, `WHISPER_VENV`, `AUDIO_ENV`, or none for this interpreter); `installs()` SHALL read each venv's deploy step so a wait no deploy step can end is visible.

#### Scenario: a package wait names the runner's venv
- **WHEN** a diffusers screen fails for a missing module
- **THEN** it is declined with reason runtime until `package:` the distribution `@` the diffusers venv, and an engine with no venv of its own gives no `@` part
Test: tests/test_missing_package_1008.py::test_the_screen_declines_it_until_the_runner_venv_has_the_package

#### Scenario: the package until is met once that venv has it
- **WHEN** the named venv gains the distribution
- **THEN** the until is met, and the same distribution in another venv does not meet it
Test: tests/test_missing_package_1008.py::test_the_package_until_is_met_once_that_venv_has_it

### Requirement: Rank by what a screen would teach, with reasons
`rank.value` SHALL score a candidate by the value of the information a screen would buy, from facts the store already holds, and every ranked row MUST carry the reasons for its score in `value_why`.

#### Scenario: Every ranked row says why
- **WHEN** `rank.rank` ranks a candidate in a lane with no run receipt
- **THEN** its `value_why` is not empty and names the lane
Test: tests/test_harness_rank.py::test_every_row_says_why_it_is_where_it_is

#### Scenario: An open lane outranks a covered one
- **WHEN** one candidate's lane has no run receipt and another's lane has one
- **THEN** the candidate in the open lane scores higher
Test: tests/test_harness_rank.py::test_a_lane_with_no_receipt_outranks_one_already_covered

#### Scenario: Recurrence counts with diminishing steps
- **WHEN** the same candidate is seen once, twice and many times
- **THEN** its score rises with each, the later step is smaller than the first, and no recurrence lifts a laneless row above a row with a lane
Test: tests/test_harness_rank.py::test_recurrence_counts_and_stops_counting

#### Scenario: A requant of a served model teaches nothing
- **WHEN** a candidate's lineage names a model this machine's gateway already serves
- **THEN** it ranks below an otherwise equal candidate with unknown lineage
Test: tests/test_harness_rank.py::test_a_requant_of_something_already_served_ranks_below_it

#### Scenario: Lineage comes from lineage rows, never prose
- **WHEN** a candidate's description says it was built from a served model but it has no lineage row
- **THEN** it scores the same as a candidate with no lineage at all
Test: tests/test_harness_rank.py::test_lineage_is_read_from_the_lineage_rows_not_the_prose

### Requirement: Lane priority breaks ties and never outranks teaching nothing
`rank.priority_of` SHALL add a share of `PRIORITY` that falls down `LANE_PRIORITY` and is zero for any lane not listed, and that share MUST NOT lift a candidate above one the lineage terms say teaches something.

#### Scenario: The priority order is pinned
- **WHEN** `LANE_PRIORITY` is read
- **THEN** it is the asked-for order with later lanes appended, and each lane's priority is no higher than the one before it
Test: tests/test_harness_rank.py::test_the_priority_order_is_the_one_that_was_asked_for

#### Scenario: A wanted lane wins a tie the alphabet would lose
- **WHEN** a candidate in a wanted lane and one in an unlisted lane carry the same information, and the unlisted one sorts first by name
- **THEN** the wanted lane's candidate ranks first
Test: tests/test_harness_rank.py::test_a_wanted_lane_outranks_an_unwanted_one_on_equal_information

#### Scenario: Priority never beats a served requant's penalty
- **WHEN** a requant of a served model sits in the top wanted lane and a fresh candidate sits in a lower live lane
- **THEN** the fresh candidate ranks first
Test: tests/test_harness_rank.py::test_priority_never_outranks_teaching_nothing

### Requirement: Only a lane can put a row in the queue
`rank.rank` SHALL drop a row no lane can test, unless the caller asks to keep the laneless, and it MUST read a row's lane only through `rank.lane_of`, where a source's `all` is no lane and `text` is the code lane.

#### Scenario: A laneless row is dropped
- **WHEN** a laneless row and a row with a lane are ranked
- **THEN** only the row with a lane is returned
Test: tests/test_harness_adopt.py::test_a_candidate_with_no_lane_is_not_ranked

#### Scenario: `all` is no lane and `text` is code
- **WHEN** rows whose stored lanes are `all` and `text` are ranked
- **THEN** the `all` row is dropped, the `text` row is kept with its stored lane unchanged, and `lane_of` reads it as `code`
Test: tests/test_harness_adopt.py::test_a_lane_of_all_counts_as_none_and_text_is_the_code_lane

### Requirement: A parked lane sinks and stays
A candidate in a parked lane SHALL score `PARKED_LANE`, below a laneless candidate, and `rank.rank` MUST keep it in the queue rather than drop it, with a reason that names what would un-park the lane.

#### Scenario: Parked ranks below laneless
- **WHEN** a parked lane's candidate and a laneless candidate are scored
- **THEN** the parked candidate scores lower
Test: tests/test_harness_lanes.py::test_a_parked_lanes_candidates_sink_below_the_laneless

#### Scenario: Parked stays in the queue, last
- **WHEN** a parked candidate and a live candidate are ranked
- **THEN** both are returned and the parked one is last
Test: tests/test_harness_lanes.py::test_a_parked_candidate_stays_in_the_queue

### Requirement: Rows the next tier would refuse never rank
`rank.rank` SHALL drop an attachment unless its lane has an engine that loads that kind, a technique, and a row whose runtime this machine lacks; whether a row is runnable MUST be answered for the machine asking and never stored as a verdict.

#### Scenario: An adapter by name is dropped, a format word alone is not
- **WHEN** a row whose name says it is a LoRA, a row whose name carries only a format word, and an ordinary model are ranked
- **THEN** the LoRA is dropped and the other two are kept
Test: tests/test_harness_lanes.py::test_an_adapter_never_reaches_the_queue

#### Scenario: An adapter stays where an engine loads it
- **WHEN** a LoRA in a lane with an adapter engine, a LoRA in a lane without one, and a node pack are ranked
- **THEN** only the LoRA whose lane loads it is returned
Test: tests/test_decide_lane.py::test_rank_keeps_an_adapter_only_where_an_engine_loads_it

#### Scenario: A technique never enters the model queue
- **WHEN** a technique and a model in the same lane are ranked
- **THEN** only the model is returned
Test: tests/test_techniques_found.py::test_a_technique_never_enters_the_model_queue

#### Scenario: Runnable is a fact about the machine asking
- **WHEN** `rank.unrunnable` is asked about a card that needs a GPU runtime, once for a machine without it and once for one with it
- **THEN** the first answer names the missing runtime and the second is empty
Test: tests/test_harness_runtime_needed.py::test_the_answer_is_a_fact_about_the_machine_asking

#### Scenario: An unrunnable row is dropped from the ranking
- **WHEN** `rank.rank` meets a row for which `rank.unrunnable` is not empty on this machine
- **THEN** the row is not returned and no verdict is written for it
Test: untested

### Requirement: Expected value against the incumbent
`rank.value` SHALL add `PEER` scaled by how close a candidate's parameter count is to the lane incumbent's, SHALL score the incumbent's own family as `KNOWN_LINEAGE`, and SHALL add `FAMILY` for a family the incumbent is built on, read from lineage rows.

#### Scenario: An old size peer screens before fresh tiny releases
- **WHEN** an old size peer of the incumbent and several fresh, recurring, much smaller releases are ranked
- **THEN** the size peer ranks first
Test: tests/test_rank_881.py::test_an_old_27b_peer_screens_before_three_fresh_sub_1b_releases

#### Scenario: The reason names the peer and the wait
- **WHEN** a size peer of the incumbent is ranked
- **THEN** its reasons name its size, the incumbent and its size, and how many days it has waited
Test: tests/test_rank_881.py::test_the_head_says_it_is_a_peer_of_the_incumbent

#### Scenario: A requant of the incumbent ranks below another family's peer
- **WHEN** a quantised child of the incumbent and a same-size peer from another family are ranked
- **THEN** the other family's peer ranks first
Test: tests/test_rank_881.py::test_a_requant_of_the_incumbent_ranks_below_a_peer_from_another_family

#### Scenario: The incumbent's base family breaks a peer tie
- **WHEN** two equal peers are ranked, first with no base families and then with one peer's family named as the incumbent's base
- **THEN** the first order follows the alphabet and the second puts the base family's peer first
Test: tests/test_rank_881.py::test_the_family_the_incumbent_is_built_on_breaks_a_peer_tie

### Requirement: Known costs and the wait
`rank.value` SHALL subtract `DECLINED` for each earlier adopt decline up to a cap, SHALL subtract `HEAVY` for weights over half the machine's ceiling, SHALL add `AGE` that ramps over `AGE_DAYS` since first sighting, and `rank.rank` SHALL subtract `QUANT_QUEUED` from a row whose quantised child is in the same queue.

#### Scenario: Adopt declines cost rank
- **WHEN** two equal peers are ranked and one was declined at adopt several times
- **THEN** the declined one ranks second
Test: tests/test_rank_881.py::test_each_adopt_decline_costs_rank

#### Scenario: Heavy weights rank below a lighter peer
- **WHEN** two equal peers are ranked and only one is over half the ceiling
- **THEN** the lighter one ranks first
Test: tests/test_rank_881.py::test_weights_over_half_the_ceiling_rank_below_a_lighter_peer

#### Scenario: A base ranks below its queued quant
- **WHEN** a full-precision base and a quantised child naming it are in one queue
- **THEN** the quant ranks first, the base's score is its lone score plus `QUANT_QUEUED`, and its reason names the quant
Test: tests/test_rank_881.py::test_a_full_precision_base_ranks_below_its_queued_quant

#### Scenario: The longer wait ranks first
- **WHEN** two otherwise equal rows differ only in first sighting
- **THEN** the one seen first ranks first
Test: tests/test_rank_881.py::test_the_longer_wait_ranks_first_on_otherwise_equal_rows

### Requirement: A row a fetch budget passes over gains rank
`rank.value` SHALL add `PASSED_OVER` for each distinct day a fetch budget refused the row while it fit the whole budget, counted since its last verdict from a later tier or a reopen, and SHALL stop at `PASSED_OVER_MAX`; `rank.rank` MUST record one `fetch_passed_over_max` cut per call when a row passes the cap.

#### Scenario: A starved row rises above fresher rows
- **WHEN** a row of lower base value is refused by the budget on enough days
- **THEN** it ranks above the fresher row and its reason counts the days
Test: tests/test_fetch_passed_over_1288.py::test_a_row_the_budget_keeps_passing_over_rises_above_fresh_rows_of_higher_base_value

#### Scenario: Only refusals of a row that fit count
- **WHEN** a row has a remainder refusal, an over-whole-budget refusal with an `until`, a waiting-on-a-base refusal, and a second remainder refusal the same day
- **THEN** `rank.passed_over` counts one day
Test: tests/test_fetch_passed_over_1288.py::test_the_pass_over_term_counts_only_refusals_of_rows_that_fit_the_whole_budget

#### Scenario: A screen verdict restarts the count
- **WHEN** a row has refusals on several days and then a screen verdict
- **THEN** its count is empty after the verdict and unchanged when read before it
Test: tests/test_fetch_passed_over_1288.py::test_the_pass_over_term_restarts_after_a_screen_verdict

#### Scenario: The cap binds and is recorded
- **WHEN** a row is passed over once more than the cap allows
- **THEN** one `limit_cuts` row is written for `fetch_passed_over_max`, and a row exactly at the cap writes none
Test: tests/test_fetch_passed_over_1288.py::test_a_row_at_the_pass_over_cap_records_a_cut

### Requirement: The order is deterministic and walks the backlog
`rank.rank` SHALL sort best value first, then by the most recent sighting, then by name, so one run's order is reproducible and a tie is not settled by the alphabet alone.

#### Scenario: A tie is stable across runs
- **WHEN** the same tied rows are ranked twice
- **THEN** both orders match and the tie falls to the name
Test: tests/test_harness_rank.py::test_the_order_is_stable_when_two_rows_tie

#### Scenario: The fresher sighting wins a tie
- **WHEN** two rows have equal value and the later name was seen more recently
- **THEN** the more recently seen row ranks first
Test: tests/test_harness_rank.py::test_the_fresher_sighting_wins_a_tie

### Requirement: The rank takes the store and never opens one
`rank.rank` and `rank.incumbents` SHALL require the store connection as an argument, MUST raise rather than open the live store or fall back to the typed defaults, and SHALL take a lane's incumbent from the store's adoption before its typed default.

#### Scenario: No store argument
- **WHEN** `rank.rank` is called without `conn`
- **THEN** it raises `TypeError`
Test: tests/test_rank_893.py::test_rank_without_a_store_is_a_type_error

#### Scenario: A None store raises and opens nothing
- **WHEN** `rank.incumbents` or `rank.rank` is given `conn=None` without explicit incumbents
- **THEN** each raises `ValueError` and no store is opened
Test: tests/test_rank_893.py::test_a_none_store_raises_instead_of_opening_the_live_one

#### Scenario: An adoption wins over the typed default
- **WHEN** the store records an adoption in one lane
- **THEN** that lane's incumbent is the adopted model and every other lane keeps its typed default
Test: tests/test_rank_893.py::test_an_adopted_incumbent_wins_over_the_typed_one

### Requirement: Fetch and screen share one order
The fetch tier and the screen tier SHALL order candidates by the same `rank.rank` call against the same store, so the disk is spent on what the next tier will run.

#### Scenario: The fetch order is the screen order
- **WHEN** the fetch queue and the screen's ranking are read for one lane from one store
- **THEN** the two orders are equal
Test: tests/test_harness_fetching_order.py::test_the_fetch_order_is_the_screen_order

#### Scenario: Both read the incumbent's lineage
- **WHEN** the incumbent's base family is known only from a lineage row
- **THEN** the fetch queue and the screen plan put that family's peer first, in the same order
Test: tests/test_rank_881.py::test_the_fetch_and_the_screen_read_the_incumbents_lineage_alike

### Requirement: Laneless candidates are reported for a person to decide
`rank.wanted` SHALL list recurring laneless candidates that are neither attachments, tools nor techniques, most seen first, and `rank.wanted_groups` SHALL group them by task with evidence and MUST NOT decide a lane.

#### Scenario: A recurring adapter is not a lane wanted
- **WHEN** recurring laneless rows include adapters and a model with a task
- **THEN** only the model is listed
Test: tests/test_lanes_wanted.py::test_an_adapter_that_recurs_is_not_a_lane_wanted

#### Scenario: A tool repo is a tool, not a lane
- **WHEN** a code-hosting repo with no task and a model with a task recur laneless
- **THEN** `wanted` lists the model and `tools_wanted` lists the repo
Test: tests/test_lanes_wanted.py::test_a_github_repo_with_no_task_is_a_tool_not_a_lane

#### Scenario: An unlisted task is unknown
- **WHEN** a task is not in `MEASURABLE`
- **THEN** `metric_for` returns empty rather than calling it unmeasurable
Test: tests/test_lanes_wanted.py::test_an_unlisted_task_is_unknown_never_unmeasurable

### Requirement: A family is its lineage root
`family.root` SHALL follow a candidate's first lineage parent to its end and `family.key` SHALL name the family by that root's basename less a format suffix and a `-base` suffix; the walk MUST stop at a cycle, before a parent more than `SIZE_RATIO` times larger or smaller, and after `HOPS` hops, recording a `family_hops` cut when it stops for length.

#### Scenario: The chain ends at the root and a cross-size parent ends it
- **WHEN** a quant names a fine-tune whose chain reaches a base, a model names a much smaller parent, and two names are each other's parent
- **THEN** the quant's family is the base's key, the mismatched model is its own family, and the cycle stops
Test: tests/test_family_1100.py::test_the_root_is_the_end_of_the_lineage_chain_and_a_cross_size_parent_ends_it

#### Scenario: A chain past the hops is a cut
- **WHEN** a chain within `HOPS` and one longer are walked
- **THEN** the short one records nothing and the long one records one `family_hops` cut
Test: tests/test_knob_use_cuts_734.py::test_a_lineage_past_the_hops_is_a_cut_and_a_short_one_is_not

### Requirement: Each family's paired record per lane
`family.standing` SHALL read the adopt tier's candidate verdicts that measured or declined, per lane and family, counting each distinct losing member since the family's last win in that lane; a win MUST clear the losses, and a method crossing MUST NOT count as a member.

#### Scenario: Repeated losses by one member count once
- **WHEN** one member is declined several times
- **THEN** every verdict is counted but the family is not demoted
Test: tests/test_family_1100.py::test_repeated_losses_by_one_member_count_once

#### Scenario: A win clears the demotion
- **WHEN** a demoted family's member wins and then another member loses
- **THEN** the sibling regains its place after the win and keeps it after the single later loss
Test: tests/test_family_1100.py::test_a_win_by_any_member_clears_the_demotion

#### Scenario: Losses in another lane do not count here
- **WHEN** a family's members lose `LOSSES_TO_DEMOTE` times in another lane
- **THEN** its sibling keeps its place in this lane
Test: tests/test_family_1100.py::test_losses_in_another_lane_do_not_demote_here

#### Scenario: A method crossing is not a member
- **WHEN** method crossings of a model are declined at adopt
- **THEN** the standing holds no family
Test: tests/test_family_1100.py::test_a_method_crossing_is_not_a_family_member

### Requirement: A family that keeps losing ranks lower
Once `LOSSES_TO_DEMOTE` distinct members of a family have lost in a lane, `Standing.demotion` SHALL give the family's other members `DEMOTION` in that lane with a reason that counts the losses; a member whose name carries a word `LANE_TRAINING` lists for the lane, and the root's own weights while no form of them lost, MUST be exempt, with the exemption in the reason.

#### Scenario: A sibling falls below an unrelated candidate
- **WHEN** one loss short of `LOSSES_TO_DEMOTE` and then at it
- **THEN** the sibling keeps its place first and then ranks below the unrelated candidate, with a reason naming the count and the lane
Test: tests/test_family_1100.py::test_after_n_losses_a_sibling_ranks_below_an_unrelated_candidate_it_used_to_outrank

#### Scenario: A lane-trained member is exempt and says so
- **WHEN** a demoted family's member names training for the lane
- **THEN** it keeps its place and its reason says it is exempt and names the word
Test: tests/test_family_1100.py::test_a_lane_specific_card_is_exempt_and_the_exemption_is_recorded

#### Scenario: An unlisted word or lane is not exempt
- **WHEN** a name's word is not in `LANE_TRAINING` for the lane, or names another lane's training
- **THEN** `family.exempt` returns empty
Test: tests/test_family_1100.py::test_a_name_or_lane_the_training_table_does_not_list_is_not_exempt

#### Scenario: The base is not demoted for its derivatives' losses
- **WHEN** only derivatives of a base lost
- **THEN** the base's own weights in any format or under a publisher prefix get no demotion and a reason saying only its derivatives lost, while a derivative sibling is demoted
Test: tests/test_fetch_passed_over_1288.py::test_a_familys_unmeasured_base_is_not_demoted_for_its_derivatives_losses

#### Scenario: The base is demoted once a form of it lost
- **WHEN** one of the losers is a form of the base itself
- **THEN** the base's other forms take `DEMOTION`
Test: tests/test_fetch_passed_over_1288.py::test_a_familys_base_forms_are_demoted_once_a_base_form_lost

### Requirement: The measure plan puts demoted families last and holds a diversity slot
`family.measure_order` SHALL move demoted families' members after the rest, each part in its own order, and `family.reserve` SHALL move up to `SLOTS` of the highest-placed rows whose family has no paired comparison in its lane within `WINDOW_DAYS` to the head, one per family, never a method crossing or a demoted family; a pick that does not fit MUST give its slot back and say so.

#### Scenario: An unmeasured family placed last makes the plan
- **WHEN** ten rows of one compared family are followed by one row of a never-compared family and the plan is shorter than the queue
- **THEN** the never-compared row is first and the rest follow in their order
Test: tests/test_family_1100.py::test_ten_same_family_rows_and_an_unmeasured_family_last_the_plan_includes_it

#### Scenario: No slots, no pick
- **WHEN** the plan is built with zero slots
- **THEN** the never-compared row is not in it and the line says no slot is held
Test: tests/test_family_1100.py::test_with_no_diversity_slots_the_plan_does_not_include_it

#### Scenario: A family compared before the window qualifies again
- **WHEN** a family's last paired comparison is older than the window
- **THEN** its highest-placed row takes the slot
Test: tests/test_family_1100.py::test_a_family_compared_before_the_window_qualifies_again

#### Scenario: A pick that does not fit gives its slot back
- **WHEN** the only qualifying row does not fit
- **THEN** no pick is made, the queue is unchanged, and the lines name the row with why and say the slot returns to the normal queue
Test: tests/test_family_1100.py::test_a_pick_that_does_not_fit_gives_its_slot_back_and_says_so

#### Scenario: A demoted family never takes a slot
- **WHEN** a demoted family's row is considered inside and outside the window
- **THEN** it is never picked
Test: tests/test_family_1100.py::test_a_demoted_family_never_takes_a_diversity_slot

#### Scenario: The measure step applies both
- **WHEN** the sweep's measure queue holds a demoted family's row first and a never-compared family's row last
- **THEN** the never-compared row leads, the demoted row is last, the pick is noted for the morning, and the step says the demoted row waits behind the rest
Test: tests/test_family_1100.py::test_the_measure_step_puts_a_demoted_family_last_and_the_pick_first

### Requirement: `soh families` shows the family terms as a dry run
`soh families` SHALL read a snapshot copy of the store and print each family's paired record per lane, the chosen lane's queue with and without the family term, and tonight's measure plan with and without the diversity slot; its what-if flags MUST rebind the family constants for that process only and MUST NOT change the store.

#### Scenario: What-if flags rebind for one run
- **WHEN** `soh families` runs with `--losses`, `--window-days`, `--slots` or `--demotion`
- **THEN** `LOSSES_TO_DEMOTE`, `WINDOW_DAYS`, `SLOTS` or `DEMOTION` take that value for this process and the report states the values it used
Test: untested

#### Scenario: The plan is a dry run
- **WHEN** `soh families` builds tonight's plan
- **THEN** it calls the sweep's measure queue with a room check that admits every row, once with the slot and once with zero slots, and says that a dry run checks no memory
Test: untested

### Requirement: Every queued row gets a state and a reason
The screen plan in harness/screen.py SHALL give every row it is handed one of `ready`, `waiting-on-fetch` or `no-runner` with a reason, and SHALL NOT drop a row it cannot run. A row with no spelling or with a runner gap SHALL be answered without consulting the weights cache.

#### Scenario: Weights absent
- **WHEN** a runnable candidate's own weights are not on disk
- **THEN** its state is `waiting-on-fetch` and its reason names `soh fetch`
Test: tests/test_harness_screen.py::test_a_candidate_whose_weights_are_absent_is_waiting_not_failed

#### Scenario: Its config names a repo that is absent
- **WHEN** the candidate is on disk but a repo its config names is not
- **THEN** it is `waiting-on-fetch` and the reason names the missing repo
Test: tests/test_harness_screen.py::test_a_model_whose_config_names_an_absent_repo_is_not_ready

#### Scenario: Everything present
- **WHEN** nothing the candidate needs is missing
- **THEN** its state is `ready`
Test: tests/test_harness_screen.py::test_a_model_with_everything_present_is_ready

#### Scenario: No lane, no disk lookup
- **WHEN** a row has no lane
- **THEN** it is `no-runner` with a reason saying it has no lane
- **AND** the weights cache is never asked about it
Test: tests/test_harness_screen.py::test_a_lane_with_no_runner_is_not_asked_about_weights

#### Scenario: A runner gap, no disk lookup
- **WHEN** a spelled row has a runner gap, such as no case fitting its method
- **THEN** it is `no-runner` with that gap as its reason
- **AND** the weights cache is never asked about it
Test: tests/test_screen_case_fit.py::test_a_spelled_row_with_a_case_gap_is_not_asked_about_weights

#### Scenario: An attachment says what it is
- **WHEN** a row's stored `attaches_to` column names a lora
- **THEN** it is `no-runner` and the reason says it attaches to a model
Test: tests/test_harness_screen.py::test_the_state_says_why_rather_than_no_runner

### Requirement: One spelling per candidate, none for an attachment
`candidate_for` SHALL return the spec of the first engine in the lane's `LANE_CANDIDATES` entry that can run the model, SHALL pass an already-spelled spec through unchanged, and SHALL return an empty spec only for an attachment no engine of the lane loads or a row with no lane. `is_attachment` SHALL call a row an attachment only from whole tags, a drafter's architecture, or a listing that says so; a row with no description, or a tag in `NOT_A_MODEL_EXCEPTIONS`, SHALL stay a candidate.

#### Scenario: Spelling twice is spelling once
- **WHEN** a lane's spelling of a model is spelled again for the same lane
- **THEN** the result is unchanged
Test: tests/test_harness_screen_spec.py::test_it_is_idempotent_for_every_lane_that_has_a_spelling

#### Scenario: The first engine that takes it wins
- **WHEN** the image lane's first engine refuses a model and its second takes it
- **THEN** the second engine's spec is returned
Test: tests/test_screen_case_fit.py::test_the_first_engine_that_takes_the_model_wins

#### Scenario: A lora has no spelling
- **WHEN** an image candidate attaches to a model as a lora
- **THEN** `candidate_for` returns an empty spec
Test: tests/test_harness_screen.py::test_a_lora_is_refused_before_anything_downloads

#### Scenario: A drafter by config architecture
- **WHEN** a config lists an architecture ending in `DraftModel`
- **THEN** the row is a drafter and an attachment of kind `DRAFTER`
Test: tests/test_drafters_1039.py::test_a_config_architecture_ending_draftmodel_is_a_drafter_and_an_attachment

#### Scenario: Silence is not an adapter
- **WHEN** a row has no description
- **THEN** it is not an attachment and still gets its lane's spelling
Test: tests/test_harness_screen.py::test_a_candidate_with_no_description_is_not_assumed_to_be_an_adapter

### Requirement: Runner gaps are named before a download
`runner_gap` SHALL answer a lane in `lanes.BY_HAND` with what runs it by hand, a card naming a library in `FOREIGN_LIBRARIES` with that library, and a lane whose cases fit no method of the candidate with every case and the methods it takes.

#### Scenario: A by-hand lane
- **WHEN** a by-hand lane is asked about, in any case or spacing
- **THEN** the gap says that lane runs by hand under its canonical name
Test: tests/test_harness_screen.py::test_a_by_hand_lane_says_it_runs_by_hand_under_its_canonical_name

#### Scenario: The case gap names every case
- **WHEN** no case in the lane takes the candidate's method
- **THEN** the gap lists each case with the methods it takes
Test: tests/test_screen_case_fit.py::test_the_gap_names_every_case_and_the_methods_it_takes

### Requirement: The screen command and its gateway
`argv` SHALL run `evals.run` with `--screen`, `--repeat 1`, the row's modality and candidate, `--out` when given an outdir, and `--gateway` only when `routed_gateway` names one. `routed_gateway` SHALL send an alias the gateway knows through the gateway and a repo id to the hot-swap upstream, in the form `--gateway` takes.

#### Scenario: Screen flags, one repeat, no quality metric
- **WHEN** a ready row's command is built
- **THEN** it carries `--screen` and `--repeat 1` and no adherence metric
Test: tests/test_harness_screen.py::test_the_command_is_a_screen_with_one_repeat_and_no_metrics

#### Scenario: A repo id goes to the upstream
- **WHEN** the candidate is a repo id and the config marks a hot-swap upstream
- **THEN** the override is that upstream's base without its version path, while the config keeps its own base
Test: tests/test_harness_screen.py::test_a_repo_id_goes_to_the_upstream

### Requirement: A screen verdict comes from this run's receipt
`outcome` SHALL record `screened` when this candidate's receipt row passed a case, `broken` when the run exited non-zero or wrote no rows with no stderr class, and `queued` with reason harness when the receipt names another candidate. The receipt key SHALL be matched through the key the runner wrote, not by string equality with the spec.

#### Scenario: A pass is screened and not terminal
- **WHEN** a receipt row reports a passed case
- **THEN** the verdict is `screened`, which is not terminal
Test: tests/test_harness_screen.py::test_a_screen_that_passed_is_screened_and_not_terminal

#### Scenario: Did not run
- **WHEN** the screen exited non-zero with no receipt and no stderr class
- **THEN** the verdict is `broken`, which is terminal
Test: tests/test_harness_screen.py::test_a_screen_that_did_not_run_is_broken_and_terminal

#### Scenario: Another candidate's receipt
- **WHEN** the receipt names only another candidate
- **THEN** the verdict is `queued`, reason harness, failure class harness error
Test: tests/test_screen_listing_984.py::test_a_receipt_for_another_candidate_is_a_harness_error

#### Scenario: The spec and the key differ in spelling
- **WHEN** the receipt key is the one the candidate's engine actually writes
- **THEN** no mismatch is found
Test: tests/test_screen_evidence.py::test_a_spec_matches_the_receipt_key_it_actually_produces

### Requirement: A zero-pass screen is declined, never broken
A screen that ran, exited zero and passed nothing with no failure class, `content_failed` or `degenerate` SHALL be `declined` with reason limit, waiting on the `screen_until` the run wrote, else on `screen_limit` (screen_size for an engine in `MEDIA_ENGINES`, screen_cases otherwise). Its detail SHALL carry the checker's failures, the run's `screen_caveat`, and `SAMPLER_CHECK` when degenerate.

#### Scenario: Passed nothing
- **WHEN** a text screen passes zero cases on content
- **THEN** the verdict is declined, reason limit, until on screen_cases, met once that limit rises
Test: tests/test_screen_fair.py::test_a_screen_that_passes_nothing_is_declined_with_the_limit_that_reopens_it

#### Scenario: The run's own until wins
- **WHEN** the receipt row carries a `screen_until`
- **THEN** the declined verdict waits on exactly that until
Test: tests/test_screen_fair.py::test_the_until_the_screen_run_wrote_is_the_one_the_verdict_waits_on

#### Scenario: A media screen
- **WHEN** a diffusers screen passes nothing with no `screen_until`
- **THEN** it waits on the screen size
Test: tests/test_screen_fair.py::test_a_media_screen_that_passes_nothing_waits_on_the_screen_size

#### Scenario: The checker's reason is the detail
- **WHEN** the row's failures name a missing file
- **THEN** the declined detail quotes that failure
Test: tests/test_screen_evidence.py::test_a_failing_screen_records_the_checkers_reason

#### Scenario: A degenerate screen
- **WHEN** the row's class is degenerate and it carries a caveat
- **THEN** the detail ends with the caveat joined to `SAMPLER_CHECK`
Test: tests/test_screen_listing_984.py::test_a_degenerate_screen_joins_its_caveat_to_the_sampler_check

### Requirement: A lane's own metric can show a zero-pass model working
`working` SHALL make a zero-pass screen `screened` when any row has a positive `decide_accuracy`, or when a lane in `WER_SCREENED` heard the clips at or under `SCREEN_MAX_WER` on the candidate's own row; a claims screen SHALL NOT be screened when its balanced score is no better than an always-empty reply.

#### Scenario: A right decide field
- **WHEN** a decide row passed no case but has a positive decide accuracy
- **THEN** the verdict is `screened` with reason candidate
Test: tests/test_decide_lane.py::test_a_decide_screen_with_a_right_field_and_no_whole_case_right_is_screened

#### Scenario: A plausible transcript
- **WHEN** an stt candidate's own row, under its runner's key, has a corpus WER under the limit
- **THEN** it is `screened`, and read without that key it is declined
Test: tests/test_stt_screen_power_1007.py::test_a_plausible_transcript_screens_the_candidate_on_its_own_row_under_its_runners_key

#### Scenario: Abstaining is not working
- **WHEN** a claims screen only abstained
- **THEN** it is not `screened`
Test: tests/test_claims_balanced_metric.py::test_a_claims_screen_that_only_abstained_is_not_screened

### Requirement: A runner's failure class decides the verdict
`decide_class` SHALL take the outcome and reason from `reasons.CLASSES` and SHALL attach the until that reopens it: a limit names `limit:<the limit>`, a runtime gap names what its cause lacks (else a newer release of the engine's runtime), a GPU fault names more total memory than this machine has, and a llama-server plan refusal names `plan:<stem>`.

#### Scenario: Every class has its verdict
- **WHEN** a runner reports any known class
- **THEN** the outcome, reason and failure class are that class's
Test: tests/test_verdict_reasons.py::test_a_runner_class_decides_the_screen_verdict

#### Scenario: Limit, runtime and GPU untils
- **WHEN** a screen stops at a timeout limit, a load failure, or a GPU fault
- **THEN** the untils are the limit, a newer mlx-lm, and more total memory
Test: tests/test_verdict_reasons.py::test_a_terminal_limit_or_runtime_verdict_says_what_reopens_it

#### Scenario: A runtime gap waits on its cause
- **WHEN** the why and evidence together say a model type is not supported
- **THEN** the until names the runner that supports it
Test: tests/test_screen_listing_984.py::test_a_runtime_gap_reads_its_why_and_evidence_as_one_text

#### Scenario: Our plan refused it
- **WHEN** the failure says the llama-server plan refused the stem before any load
- **THEN** the verdict is declined, reason limit, until `plan:<stem>`, with the refusal in its detail
Test: tests/test_plan_refusal_1047.py::test_a_refusal_in_the_reason_reads_on_into_its_evidence_as_one_sentence

#### Scenario: Loader failures are never broken
- **WHEN** a diffusers layout gap, a dead server, a gateway refusal or an architecture gap fails a case
- **THEN** the verdict is not `broken`
Test: tests/test_screen_evidence.py::test_no_loader_failure_is_recorded_broken

### Requirement: Stderr is evidence only without a receipt
`verdict_of_run` SHALL classify the stderr tail once and only when the run wrote no receipt; a receipt SHALL always win. `screen_detail` SHALL keep the receipt's reason alone when there is a receipt, and otherwise append the stderr tail with Python warnings and their quoted lines removed.

#### Scenario: A receipt beats a refusal in stderr
- **WHEN** stderr says connection refused and there is no receipt, then again beside a foreign receipt
- **THEN** the first is `queued` as refused by gateway and the second is the foreign-receipt verdict
Test: tests/test_screen_evidence.py::test_a_refusal_in_stderr_counts_only_when_the_run_wrote_no_receipt

#### Scenario: A screen that could not start
- **WHEN** stderr shows the run could not import its package or find its tool
- **THEN** the verdict is `queued` and says nothing about the candidate
Test: tests/test_harness_screen_spec.py::test_a_screen_that_could_not_start_is_requeued_not_broken

#### Scenario: Detail with a receipt
- **WHEN** the run wrote a receipt and stderr holds warnings and load chatter
- **THEN** the detail is the verdict's reason alone
Test: tests/test_harness_screen.py::test_a_screen_with_a_receipt_records_no_stderr_in_its_detail

#### Scenario: Detail without a receipt
- **WHEN** there is no receipt and stderr holds a warning and a traceback
- **THEN** the detail is the reason, a separator, and the traceback without the warning
Test: tests/test_harness_screen.py::test_a_screen_without_a_receipt_keeps_its_stderr_less_warnings

### Requirement: The screen step plans from the whole queue and never downloads
`_report_screen` SHALL plan from every queueable row scoped to the lane before any count is taken, SHALL draw its ready rows from the whole plan in rank order, SHALL only list what it would run without `--run`, and SHALL return zero when nothing is ready.

#### Scenario: Scope before limiting
- **WHEN** one image row sits behind many code rows and the step is scoped to image
- **THEN** the image row is listed
Test: tests/test_harness_cli_queue_scope.py::test_the_screen_tier_scopes_before_limiting_too

#### Scenario: A ready row below the rank head
- **WHEN** the head of the plan is waiting on fetch and a fetched row sits below it
- **THEN** the listing counts one ready and names the fetched row
Test: tests/test_harness_cli_queue_scope.py::test_a_fetched_candidate_below_the_rank_head_is_still_screened

#### Scenario: Nothing ready
- **WHEN** `--run` is given and no row is ready
- **THEN** it says so and returns zero
Test: tests/test_harness_screen.py::test_an_empty_screen_is_a_result_not_a_failure

### Requirement: Weights an offline load cannot open go back to fetch
Before screening a ready row, the step SHALL ask `snapshot_gap` whether an offline load can open its recorded weights and those its config requires; when it cannot, the step SHALL stand the download down, record `queued` at the fetch tier with reason harness, and start no process. A run whose class is in `reasons.REFETCH` SHALL also be stood down and recorded at the fetch tier.

#### Scenario: A snapshot with no ref
- **WHEN** a recorded complete hub snapshot has no ref an offline load can resolve
- **THEN** no screen runs, the verdict is queued at fetch with reason harness naming the ref, and the download is no longer had
Test: tests/test_harness_screen.py::test_a_recorded_snapshot_offline_loads_cannot_open_goes_back_to_fetch

#### Scenario: A short copy
- **WHEN** the load log shows our copy is shorter than its header says
- **THEN** the verdict is queued at fetch with reason harness and the download is no longer had
Test: tests/test_load_log_953.py::test_the_screen_sends_a_short_copy_back_to_fetch

#### Scenario: A snapshot gap does not spend a slot
- **WHEN** the first ready row has a snapshot gap and the limit is one
- **THEN** the next ready row is still screened
Test: untested

### Requirement: Memory deferrals do not spend the screen or hold the fetch
A ready row that does not fit in memory now SHALL be recorded `queued` at the screen tier with reason memory and an until from `memory.wait_for`, SHALL NOT count against the screen limit, and SHALL leave the fetch backlog. Once `memory_deferrals` counts `MEMORY_DEFERRALS` newest verdicts in a row deferred for one need, a further deferral for that need SHALL record a cut instead of another verdict.

#### Scenario: A deferral waits for room
- **WHEN** a candidate needs more than is safely available
- **THEN** it is queued for memory, nothing runs, and its until is met only once enough room opens
Test: tests/test_until_keys_928.py::test_a_memory_deferral_waits_for_the_room_its_candidate_needs

#### Scenario: A deferred leftover does not hold the ranked ones back
- **WHEN** an on-disk leftover is deferred for memory beside ranked rows
- **THEN** the ranked rows are fetched and screened up to the limit
Test: tests/test_loop_backpressure.py::test_a_memory_deferred_leftover_lets_the_ranked_ones_fetch_and_screen

#### Scenario: The streak counts one need
- **WHEN** older deferrals name one need and the newest several name another
- **THEN** the streak counts only the newest need's run
Test: tests/test_loop_backpressure.py::test_the_streak_counts_one_need_only

#### Scenario: A long same-need streak stops writing
- **WHEN** a row deferred for the same need has reached `MEMORY_DEFERRALS`, has not, or reached it for a different need
- **THEN** only the first writes no new verdict
Test: tests/test_loop_backpressure.py::test_a_long_same_need_deferral_stops_writing_a_verdict_each_night

### Requirement: The fetch backlog counts only what a screen could take now
`screenable_backlog` SHALL filter the plan before anything counts it, keeping a name only when the row is ready, is not a method crossing, fits in memory now with one request's cache, and its newest verdict is not a screen memory deferral.

#### Scenario: Only ready rows that fit
- **WHEN** the plan holds a ready row, a ready row too big for memory, and a waiting row
- **THEN** only the first is backlog
Test: tests/test_loop_backpressure.py::test_the_backlog_counts_only_what_the_screen_could_take_now

#### Scenario: A memory-deferred row is not backlog
- **WHEN** a ready row's newest verdict is a screen memory deferral
- **THEN** it is left out of the backlog
Test: tests/test_loop_backpressure.py::test_a_memory_deferred_candidate_is_not_backlog

#### Scenario: A method crossing is not backlog
- **WHEN** a ready method crossing sits beside a fetched model
- **THEN** only the model is backlog
Test: tests/test_methods.py::test_a_crossing_waiting_for_a_screen_never_holds_back_a_download

### Requirement: One screen at a time under the eval lock, bounded and cleaned up
Each started screen SHALL hold the eval lock with the deadline `deadline_s` gives its candidate, SHALL be counted against the screen limit, SHALL NOT start when `out_of_time` says it would end past the sweep's screen share, SHALL record the verdict's failure class, and SHALL release its model from the router and the mlx server afterwards. A verdict whose class is in `reasons.STOPS` SHALL end the step with status one.

#### Scenario: A video screen declares its deadline
- **WHEN** a diffusers-video candidate is screened
- **THEN** the heartbeat's deadline during the run is `deadline_s` for that spec
Test: tests/test_liveness_705.py::test_a_video_screen_declares_its_engines_deadline

#### Scenario: Past the screen share
- **WHEN** a screen started now would end after the share's end, or no end is set
- **THEN** `out_of_time` is true only in the first case
Test: tests/test_lane_heads_1084.py::test_a_screen_that_would_end_past_its_share_is_not_started

#### Scenario: The failure class is stored
- **WHEN** a screen fails on a diffusers layout gap
- **THEN** the stored state is declined, waiting on the runner, with that failure class
Test: tests/test_runner_gap_until_950.py::test_a_screen_verdict_records_its_failure_class

#### Scenario: Each screened model is released
- **WHEN** a screen finishes
- **THEN** its spec is released from the router and the mlx server, naming the row
Test: tests/test_router_unload.py::test_the_screen_unloads_each_candidate_it_ran

#### Scenario: A dead server stops the step
- **WHEN** the first screen's class is a dead server
- **THEN** the second is never run and the step returns one
Test: tests/test_screen_server_death.py::test_a_dead_server_stops_the_screen

#### Scenario: The screen process cannot start
- **WHEN** starting the screen process raises an OS error
- **THEN** the row is recorded queued at the screen tier with reason harness and the step moves on
Test: untested

### Requirement: Load-log and drafter verdicts are settled where they belong
A verdict of class load_log_unread SHALL be re-decided from the router's log, kept beside the run; a verdict of class attachment SHALL mark the proposal a `DRAFTER` and record its decline at the fetch tier.

#### Scenario: The child's log decides it
- **WHEN** llama-server failed to load the candidate and its log names the cause
- **THEN** the log excerpt is kept in the run directory and the verdict comes from it
Test: tests/test_load_log_953.py::test_the_screen_keeps_the_childs_log_and_decides_from_it

#### Scenario: A drafter is held at fetch
- **WHEN** the load log shows the candidate is a drafter
- **THEN** it is marked a drafter and declined at the fetch tier with no retest and no until
Test: tests/test_drafters_1039.py::test_the_screen_holds_a_drafter_at_fetch_so_no_retest_refetches_it

### Requirement: The case count comes from the incumbent's measured rate
`cases_needed` SHALL return the fewest cases at which a model passing each at the given rate fails them all with chance under the miss, and one at a rate of one. `incumbent_measure` SHALL read the served incumbent's stored measure draws by its candidates row, not by its current spelling, and SHALL fall back to `power.UNSEEN`, saying so on stderr, when none are stored or the store cannot be read.

#### Scenario: The count from a rate
- **WHEN** the count is asked for the decide incumbent's rate
- **THEN** that count misses under the bound and one fewer does not
Test: tests/test_screen_fair.py::test_the_case_count_comes_from_the_incumbent_rate

#### Scenario: Rows under the served model's old name
- **WHEN** the incumbent's measure rows were stored under an older receipt key
- **THEN** the rate is read from them
Test: tests/test_screen_fair.py::test_the_incumbent_rate_comes_from_the_rows_measure_stored_under_the_served_model_s_old_name

#### Scenario: No stored draws
- **WHEN** no draws are found
- **THEN** the measure is `power.UNSEEN` and unmeasured, at every value of its knob
Test: tests/test_screen_fair.py::test_the_unseen_rate_knob_sets_both_an_unmeasured_screen_count_and_an_unmeasured_adopt_plan

#### Scenario: The store cannot be read
- **WHEN** reading the incumbent's rows raises
- **THEN** stderr says so and the measure is `power.UNSEEN`, unmeasured
Test: untested

### Requirement: Fetch downloads what was queued within a budget
`cmd_fetch` SHALL emit an empty queue when nothing is queued, SHALL only list without `--run`, SHALL take its budget from the download budget knob when none is given, and SHALL return zero when a rate-limited listing defers the rest of the tier.

#### Scenario: The registered budget
- **WHEN** a manual run is given no budget
- **THEN** the fetch runs with the registered download budget
Test: tests/test_fetch_retention_704.py::test_a_manual_run_with_no_budget_uses_the_registered_budget

#### Scenario: A rate-limited listing
- **WHEN** the registry answers every listing with a rate limit
- **THEN** the tier stops after its attempts and returns zero
Test: tests/test_fetch_ratelimit.py::test_a_rate_limited_listing_defers_the_rest_of_the_tier_and_exits_0

#### Scenario: A replay leaves the rank unchanged
- **WHEN** `soh fetch --replay` runs with pass-over overrides
- **THEN** the rank's pass-over step and cap are restored afterwards
Test: untested

### Requirement: The judge scores inspected fits from source facts
`_judge_fits` SHALL describe each fit to the judge with its name, what inspect read from its source and its runtime, SHALL record the score as a judge-tier `queued` verdict, and SHALL go on to the next fit when one score fails.

#### Scenario: The item carries the source facts
- **WHEN** an MLX-native fit is judged
- **THEN** the judge's item carries its name, the inspected verdict, the runtime and its description
Test: tests/test_harness_cli.py::test_judging_an_inspected_candidate_uses_only_fields_fit_has

#### Scenario: One failure does not stop the rest
- **WHEN** scoring one fit raises
- **THEN** the next fit is still scored
Test: tests/test_harness_cli.py::test_a_judge_failure_on_one_candidate_does_not_stop_the_rest
