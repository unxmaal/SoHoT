table adoptions [('id', 'INTEGER', 0, None, 1), ('lane', 'TEXT', 1, None, 0), ('candidate_id', 'INTEGER', 1, None, 0), ('incumbent_id', 'INTEGER', 0, None, 0), ('run_id', 'INTEGER', 0, None, 0), ('verdict_id', 'INTEGER', 0, None, 0), ('machine_id', 'INTEGER', 0, None, 0), ('how', 'TEXT', 1, None, 0), ('adopted_at', 'REAL', 1, None, 0), ('all_machines', 'INTEGER', 1, '0', 0), ('votes', 'INTEGER', 0, None, 0), ('agreement', 'REAL', 0, None, 0), ('forced', 'INTEGER', 1, '0', 0), ('cost', 'TEXT', 1, "'{}'", 0)]
  index ix_adoptions_lane unique=0 ['lane', 'adopted_at']
  index sqlite_autoindex_adoptions_1 unique=1 ['verdict_id']
  (1, 'code', 1, 2, 1, 14, 1, 'measured', 1789039200.0, 0, None, None, 0, '{}')
  (2, 'svg', 7, None, None, 21, 4, 'by-hand', 1789824000.0, 0, 2, 1.0, 0, '{}')
table benchmarks [('id', 'INTEGER', 0, None, 1), ('name', 'TEXT', 1, None, 0), ('lane', 'TEXT', 1, None, 0), ('registry', 'TEXT', 1, "''", 0), ('url', 'TEXT', 1, "''", 0), ('license', 'TEXT', 1, "''", 0), ('gated', 'TEXT', 1, "''", 0), ('created', 'TEXT', 1, "''", 0), ('updated', 'TEXT', 1, "''", 0), ('size', 'TEXT', 1, "''", 0), ('rows', 'INTEGER', 1, '0', 0), ('task_format', 'TEXT', 1, "''", 0), ('revision', 'TEXT', 1, "''", 0), ('likes', 'INTEGER', 1, '0', 0), ('downloads', 'INTEGER', 1, '0', 0), ('description', 'TEXT', 1, "''", 0), ('first_seen', 'REAL', 1, None, 0), ('last_seen', 'REAL', 1, None, 0)]
  index sqlite_autoindex_benchmarks_1 unique=1 ['name', 'lane']
table candidate_training [('id', 'INTEGER', 0, None, 1), ('candidate', 'TEXT', 1, None, 0), ('alias', 'TEXT', 1, "''", 0), ('lane', 'TEXT', 1, "''", 0), ('cutoff', 'TEXT', 1, "''", 0), ('cutoff_source', 'TEXT', 1, "''", 0), ('datasets', 'TEXT', 1, "'[]'", 0), ('read_at', 'REAL', 1, None, 0)]
  index sqlite_autoindex_candidate_training_1 unique=1 ['candidate']
table candidates [('id', 'INTEGER', 0, None, 1), ('proposal_id', 'INTEGER', 0, None, 0), ('spec', 'TEXT', 1, None, 0), ('receipt_key', 'TEXT', 1, None, 0), ('lane', 'TEXT', 1, "''", 0), ('created_at', 'REAL', 1, None, 0)]
  index ix_cand_key unique=0 ['receipt_key']
  index ix_cand_prop unique=0 ['proposal_id']
  index sqlite_autoindex_candidates_1 unique=1 ['spec']
  (1, 1, 'llamacpp:coder-7b-Q4_K_M', 'coder-7b', 'code', 1788960000.0)
  (2, None, 'local-mid', 'local-mid', 'code', 1788960000.0)
  (3, 13, 'mflux:org-m/image-gen', 'image-gen', 'image', 1788960000.0)
  (4, 6, 'diffusers:org-f/screen-broke', 'screen-broke', 'image', 1788960000.0)
  (5, 8, 'mlx:org-h/tts-model', 'tts-model', 'tts', 1788960000.0)
  (6, None, 'kokoro', 'kokoro', 'tts', 1788960000.0)
  (7, 12, 'mlx:org-l/svg-thing', 'svg-thing', 'svg', 1788960000.0)
  (8, None, 'local-large', 'local-large', 'svg', 1788960000.0)
table contamination_probes [('id', 'INTEGER', 0, None, 1), ('model', 'TEXT', 1, None, 0), ('lane', 'TEXT', 1, "''", 0), ('case_id', 'TEXT', 1, None, 0), ('family', 'TEXT', 1, "''", 0), ('outcome', 'TEXT', 1, None, 0), ('overlap', 'REAL', 0, None, 0), ('detail', 'TEXT', 1, "''", 0), ('at', 'REAL', 1, None, 0)]
  index ix_probes_model unique=0 ['model', 'lane']
table downloads [('id', 'INTEGER', 0, None, 1), ('proposal_id', 'INTEGER', 0, None, 0), ('repo', 'TEXT', 1, "''", 0), ('kind', 'TEXT', 1, None, 0), ('path', 'TEXT', 1, None, 0), ('file', 'TEXT', 1, "''", 0), ('origin', 'TEXT', 1, "''", 0), ('source', 'TEXT', 1, "''", 0), ('bytes', 'INTEGER', 1, '0', 0), ('files', 'INTEGER', 1, '0', 0), ('complete', 'INTEGER', 1, '0', 0), ('requires', 'TEXT', 1, "'[]'", 0), ('started_at', 'REAL', 0, None, 0), ('finished_at', 'REAL', 0, None, 0), ('removed_at', 'REAL', 0, None, 0), ('removed_by', 'TEXT', 1, "''", 0), ('removal_verdict_id', 'INTEGER', 0, None, 0), ('machine_id', 'INTEGER', 0, None, 0), ('ctx', 'INTEGER', 1, '0', 0), ('ctx_trained', 'INTEGER', 1, '0', 0), ('kv_bytes_token', 'INTEGER', 1, '0', 0), ('ctx_slots', 'INTEGER', 1, '0', 0), ('ctx_why', 'TEXT', 1, "''", 0), ('ctx_at', 'REAL', 0, None, 0), ('kv_cap_bytes', 'INTEGER', 1, '0', 0), ('coresident_bytes', 'INTEGER', 1, '0', 0)]
  index ix_downloads_path unique=0 ['path']
  index ix_downloads_repo unique=0 ['repo']
  (1, 8, 'org-h/tts-model', 'hub', '/HF/hub/models--org-h--tts-model', '', 'backfill', '', 0, 0, 0, '[]', 1788672000.0, 1788672000.0, '<now>', 'absent at backfill', None, 1, 0, 0, 0, 0, '', None, 0, 0)
  (2, 1, 'org-a/coder-7b-GGUF', 'hub', '/HF/hub/models--org-a--coder-7b-GGUF', '', 'backfill', '', 0, 0, 0, '[]', 1788643200.0, 1788643200.0, '<now>', 'absent at backfill', None, 1, 0, 0, 0, 0, '', None, 0, 0)
  (3, 7, 'org-g/gguf-llama', 'gguf', '<hf>/gguf/gguf-llama-Q4_K_M.gguf', 'gguf-llama-Q4_K_M.gguf', 'backfill', '', 0, 0, 0, '[]', '<now>', '<now>', '<now>', 'absent at backfill', None, 1, 0, 0, 0, 0, '', None, 0, 0)
  (4, 6, 'org-f/screen-broke', 'hub', '/HF/hub/models--org-f--screen-broke/snapshots/0a1b2c3d', '0a1b2c3d', 'backfill', '', 3221225472, 0, 0, '[]', None, None, 1789320000.0, 'lh disk', None, 1, 0, 0, 0, 0, '', None, 0, 0)
table edges [('id', 'INTEGER', 0, None, 1), ('src', 'INTEGER', 1, None, 0), ('dst', 'INTEGER', 1, None, 0), ('relation', 'TEXT', 1, None, 0), ('note', 'TEXT', 1, "''", 0), ('shared', 'INTEGER', 0, None, 0), ('crowd', 'INTEGER', 0, None, 0), ('score', 'REAL', 0, None, 0)]
  index ix_edges_dst unique=0 ['dst']
  index ix_edges_src unique=0 ['src']
  index sqlite_autoindex_edges_1 unique=1 ['src', 'dst', 'relation']
  (1, 1, 8, 'crowd', '', 3, 12, 0.25)
table extractions [('id', 'INTEGER', 0, None, 1), ('name', 'TEXT', 1, None, 0), ('source', 'TEXT', 1, None, 0), ('reason', 'TEXT', 1, None, 0), ('at', 'REAL', 1, None, 0)]
  index sqlite_autoindex_extractions_1 unique=1 ['name', 'source', 'reason']
  (1, 'not-a-model', 'hf-trending', 'not-a-repo', 1788618000.0)
table gateway_requests [('id', 'INTEGER', 0, None, 1), ('at', 'REAL', 1, None, 0), ('alias', 'TEXT', 1, "''", 0), ('lane', 'TEXT', 1, "''", 0), ('served', 'TEXT', 1, "''", 0), ('spec', 'TEXT', 1, "''", 0), ('client', 'TEXT', 1, "''", 0), ('call_type', 'TEXT', 1, "''", 0), ('stream', 'INTEGER', 1, '0', 0), ('prompt_tokens', 'INTEGER', 0, None, 0), ('completion_tokens', 'INTEGER', 0, None, 0), ('ttft_s', 'REAL', 0, None, 0), ('total_s', 'REAL', 0, None, 0), ('tool_calls', 'INTEGER', 1, '0', 0), ('tool_calls_valid', 'INTEGER', 1, '0', 0), ('finish_reason', 'TEXT', 1, "''", 0), ('error_class', 'TEXT', 1, "''", 0), ('error_code', 'TEXT', 1, "''", 0)]
  index ix_greq_at unique=0 ['at']
table gateway_samples [('request_id', 'INTEGER', 0, None, 1), ('prompt', 'TEXT', 1, "''", 0), ('completion', 'TEXT', 1, "''", 0)]
table gateway_switches [('id', 'INTEGER', 0, None, 1), ('lane', 'TEXT', 1, None, 0), ('old_spec', 'TEXT', 1, None, 0), ('new_spec', 'TEXT', 1, None, 0), ('how', 'TEXT', 1, None, 0), ('requested_at', 'REAL', 1, None, 0), ('switched_at', 'REAL', 1, None, 0), ('in_flight', 'INTEGER', 0, None, 0), ('outcome', 'TEXT', 1, "'switched'", 0), ('reason', 'TEXT', 1, "''", 0)]
table human_votes [('id', 'INTEGER', 0, None, 1), ('lane', 'TEXT', 1, None, 0), ('run', 'TEXT', 1, "''", 0), ('case_id', 'TEXT', 1, None, 0), ('left_candidate', 'TEXT', 1, None, 0), ('right_candidate', 'TEXT', 1, None, 0), ('winner', 'TEXT', 1, "''", 0), ('shown_first', 'TEXT', 1, "''", 0), ('voter', 'TEXT', 1, "''", 0), ('machine_id', 'INTEGER', 0, None, 0), ('at', 'REAL', 1, None, 0)]
  index ix_human_votes_pair unique=0 ['lane', 'case_id', 'left_candidate', 'right_candidate']
  (1, 'svg', '', 'icon-1', 'local-large', 'svg-thing', 'svg-thing', 'left', '', None, 1789788000.0)
  (2, 'svg', '', 'icon-1', 'local-large', 'svg-thing', 'svg-thing', 'left', '', None, 1789788000.0)
  (3, 'image', '', 'cat', 'image-gen', 'screen-broke', 'image-gen', 'right', '', None, 1789788000.0)
  (4, 'image', '20260912-090000-0002-image', 'dog', 'image-gen', 'screen-broke', 'image-gen', 'left', 'judge-page', 1, 1789896000.0)
table jobs [('id', 'INTEGER', 0, None, 1), ('title', 'TEXT', 1, "''", 0), ('kind', 'TEXT', 1, "'command'", 0), ('output', 'TEXT', 1, "''", 0), ('priority', 'INTEGER', 1, '0', 0), ('argv', 'TEXT', 1, "'[]'", 0), ('cwd', 'TEXT', 1, "''", 0), ('state', 'TEXT', 1, "'pending'", 0), ('created_at', 'REAL', 1, None, 0), ('started_at', 'REAL', 0, None, 0), ('finished_at', 'REAL', 0, None, 0), ('rc', 'INTEGER', 0, None, 0), ('log', 'TEXT', 1, "''", 0), ('note', 'TEXT', 1, "''", 0), ('requested_by', 'TEXT', 1, "''", 0), ('machine_id', 'INTEGER', 0, None, 0)]
  index ix_jobs_state unique=0 ['state', 'priority']
  (1, 'soh discover', 'command', '', 0, '["soh", "discover"]', '/REPO', 'done', 1789808400.0, 1789808405.0, 1789809000.0, 0, '/LOGS/0001.log', '', 'migration', 1)
  (2, 'tts measure', 'command', '', 5, '["uv", "run", "python", "-m", "evals.run"]', '/REPO', 'failed', 1789894800.0, 1789894805.0, 1789898400.0, 1, '/LOGS/0002.log', 'one case failed', 'migration', 1)
table lineage [('id', 'INTEGER', 0, None, 1), ('proposal_id', 'INTEGER', 1, None, 0), ('parent', 'TEXT', 1, None, 0), ('kind', 'TEXT', 1, "''", 0)]
  index sqlite_autoindex_lineage_1 unique=1 ['proposal_id', 'parent', 'kind']
  (1, 4, 'org-z/base-xl', 'adapter')
table machine_merges [('id', 'INTEGER', 0, None, 1), ('from_id', 'INTEGER', 1, None, 0), ('from_fingerprint', 'TEXT', 1, None, 0), ('into_id', 'INTEGER', 1, None, 0), ('repointed', 'TEXT', 1, "'{}'", 0), ('merged_at', 'REAL', 1, None, 0)]
  (1, 2, 'Mac14,12/macOS-26.0-arm64-arm-64bit-Mach-O/arm64', 1, '{"adoptions": 0, "downloads": 0, "human_votes": 0, "jobs": 0, "memory_limits": 0, "reverifications": 0, "runs": 0, "sightings": 0, "verdicts": 0}', '<now>')
  (2, 3, 'Mac14,12//arm64', 1, '{"adoptions": 0, "downloads": 0, "human_votes": 0, "jobs": 0, "memory_limits": 0, "reverifications": 0, "runs": 1, "sightings": 0, "verdicts": 0}', '<now>')
  (3, 7, 'Mac14,12/macOS/arm64', 1, '{"adoptions": 0, "downloads": 4, "human_votes": 0, "jobs": 0, "memory_limits": 0, "reverifications": 0, "runs": 0, "sightings": 0, "verdicts": 0}', '<now>')
table machines [('id', 'INTEGER', 0, None, 1), ('fingerprint', 'TEXT', 1, None, 0), ('hw_model', 'TEXT', 1, "''", 0), ('os', 'TEXT', 1, "''", 0), ('arch', 'TEXT', 1, "''", 0), ('memory_gb', 'REAL', 1, '0', 0), ('accelerator', 'TEXT', 1, "''", 0), ('runtimes', 'TEXT', 1, "''", 0), ('ceiling_gb', 'REAL', 1, '0', 0), ('first_seen', 'REAL', 1, None, 0), ('last_seen', 'REAL', 1, None, 0), ('versions', 'TEXT', 1, "'{}'", 0)]
  index sqlite_autoindex_machines_1 unique=1 ['fingerprint']
  (1, 'Mac14,12/macOS/arm64', 'Mac14,12', 'macOS-26.0-arm64-arm-64bit-Mach-O', 'arm64', 32.0, 'metal 32GB', 'llamacpp,mlx', 23.0, 1788600000.0, '<now>', '{}')
  (4, 'Mac17,15/macOS/arm64', 'Mac17,15', 'macOS-27.0.1-arm64-arm-64bit', 'arm64', 64.0, 'metal 32GB', 'llamacpp,mlx', 23.0, 1788610800.0, 1790050800.0, '{}')
  (5, 'B650M/Linux/x86_64', 'B650M', 'Linux-6.8.0-45-generic-x86_64-with-glibc2.39', 'x86_64', 64.0, 'cuda 12GB', 'cuda,llamacpp,vllm', 23.0, 1788614400.0, 1790054400.0, '{}')
  (6, 'B650M/Windows/AMD64', 'B650M', 'Windows-11-SP0', 'AMD64', 64.0, 'cuda 12GB', 'cuda,llamacpp,vllm', 23.0, 1788618000.0, 1790058000.0, '{}')
table memory_limits [('id', 'INTEGER', 0, None, 1), ('machine_id', 'INTEGER', 1, None, 0), ('measured_at', 'REAL', 1, None, 0), ('margin_gb', 'REAL', 0, None, 0), ('last_normal_gb', 'REAL', 0, None, 0), ('stopped', 'TEXT', 1, "''", 0), ('report', 'TEXT', 1, "'{}'", 0)]
  (1, 1, 1789898400.0, 6.5, 25.5, 'floor', '{"last_normal_gb": 25.5, "margin_gb": 6.5, "measured_at": "2026-09-20T10:00:00", "stopped": "floor"}')
table meta [('key', 'TEXT', 0, None, 1), ('value', 'TEXT', 0, None, 0)]
  index sqlite_autoindex_meta_1 unique=1 ['key']
  ('artifact_split', '{"code": {"missing": 4, "none": 2, "path": 0, "resolved": 0, "text": 4}, "image": {"missing": 0, "none": 2, "path": 2, "resolved": 0, "text": 0}, "tts": {"missing": 0, "none": 0, "path": 4, "resolved": 0, "text": 0}}')
  ('candidate_guesses', '[{"adoption": 2, "from": "the adopt verdict/'s machine; no vote or judged run names one", "lane": "svg", "machine": 4, "proposal": "org-l/svg-thing", "spec": "mlx:org-l/svg-thing"}]')
  ('schema', '60')
table proposals [('id', 'INTEGER', 0, None, 1), ('name', 'TEXT', 1, None, 0), ('kind', 'TEXT', 1, "'candidate'", 0), ('registry', 'TEXT', 1, "''", 0), ('description', 'TEXT', 1, "''", 0), ('lane', 'TEXT', 1, "''", 0), ('resolved', 'TEXT', 1, "''", 0), ('first_seen', 'REAL', 1, None, 0), ('last_seen', 'REAL', 1, None, 0), ('state', 'TEXT', 1, "''", 0), ('state_verdict_id', 'INTEGER', 0, None, 0), ('retest_count', 'INTEGER', 1, '0', 0), ('next_retest_at', 'REAL', 0, None, 0), ('size_bytes', 'INTEGER', 1, '0', 0), ('hf_task', 'TEXT', 1, "''", 0), ('library', 'TEXT', 1, "''", 0), ('card_tags', 'TEXT', 1, "'[]'", 0), ('attaches_to', 'TEXT', 1, "''", 0), ('runtime_needed', 'TEXT', 1, "''", 0), ('lane_source', 'TEXT', 1, "''", 0), ('card_read', 'TEXT', 1, "''", 0), ('category', 'TEXT', 1, "''", 0), ('model_type', 'TEXT', 1, "''", 0), ('remote_code', 'TEXT', 1, "''", 0)]
  index ix_prop_state unique=0 ['state']
  index sqlite_autoindex_proposals_1 unique=1 ['name']
  (1, 'org-a/coder-7b-GGUF', 'candidate', 'huggingface', 'task text-generation; served by llamacpp; tagged gguf, code', 'code', '', 1788600000.0, 1789320000.0, 'measured', 14, 0, None, 4724464025, 'text-generation', 'llamacpp', '["gguf", "code"]', '', '', 'card', 'description', 'model', '', '')
  (2, 'org-b/huge-70b', 'candidate', 'huggingface', 'task text-generation', 'code', '', 1788603600.0, 1789323600.0, 'declined', 4, 0, None, 42412802048, 'text-generation', '', '[]', '', '', 'card', 'description', 'model', '', '')
  (3, 'org-c/old-repo', 'candidate', 'github', 'A training script for a vision model', '', '', 1788607200.0, 1789327200.0, 'declined', 5, 0, None, 0, '', '', '[]', '', '', '', 'description', 'tool', '', '')
  (4, 'org-d/lora-x', 'candidate', 'huggingface', 'task text-to-image; adapter of org-z/base-xl', 'image', '', 1788610800.0, 1789330800.0, 'ignored', 6, 0, None, 0, 'text-to-image', '', '[]', 'adapter', '', 'card', 'description', 'model', '', '')
  (5, 'org-e/vllm-only', 'candidate', 'huggingface', 'task text-generation; served by vllm', 'code', '', 1788614400.0, 1789334400.0, 'declined', 8, 0, None, 24696061952, 'text-generation', 'vllm', '[]', '', 'vllm', 'card', 'description', 'model', '', '')
  (6, 'org-f/screen-broke', 'candidate', 'huggingface', 'task text-to-image', 'image', '', 1788618000.0, 1789338000.0, 'broken', 16, 0, None, 0, 'text-to-image', '', '[]', '', '', 'card', 'description', 'model', '', '')
  (7, 'org-g/gguf-llama', 'candidate', 'huggingface', 'task text-generation; tagged gguf', 'code', '', 1788621600.0, 1789341600.0, 'declined', 9, 0, None, 0, 'text-generation', '', '["gguf"]', '', '', 'card', 'description', 'model', '', '')
  (8, 'org-h/tts-model', 'candidate', 'huggingface', 'task text-to-speech', 'tts', '', 1788625200.0, 1789345200.0, 'declined', 20, 0, 1790400000.0, 24696061952, 'text-to-speech', '', '[]', '', '', 'card', 'description', 'model', '', '')
  (9, 'org-i/queued-only', 'candidate', 'huggingface', 'a small model', 'code', '', 1788628800.0, 1789348800.0, 'queued', 12, 0, None, 24696061952, '', '', '[]', '', '', '', 'description', 'model', '', '')
  (10, 'org-j/never-judged', 'candidate', 'github', '', '', '', 1788632400.0, 1789352400.0, '', None, 0, None, 0, '', '', '[]', '', '', '', '', 'tool', '', '')
  (11, 'org-k/harness-broke', 'candidate', 'huggingface', 'task text-generation', 'code', '', 1788636000.0, 1789356000.0, 'queued', 18, 0, None, 0, 'text-generation', '', '[]', '', '', 'card', 'description', 'model', '', '')
  (12, 'org-l/svg-thing', 'candidate', 'huggingface', 'task text-generation; tagged svg', 'svg', '', 1788639600.0, 1789359600.0, 'measured', 21, 0, None, 0, 'text-generation', '', '["svg"]', '', '', '', 'description', 'model', '', '')
  (13, 'org-m/image-gen', 'candidate', 'huggingface', 'task text-to-image', 'image', '', 1788643200.0, 1789363200.0, 'screened', 15, 0, None, 0, 'text-to-image', '', '[]', '', '', 'card', 'description', 'model', '', '')
table results [('id', 'INTEGER', 0, None, 1), ('run_id', 'INTEGER', 1, None, 0), ('seq', 'INTEGER', 1, None, 0), ('candidate_id', 'INTEGER', 0, None, 0), ('candidate', 'TEXT', 1, None, 0), ('case_id', 'TEXT', 1, None, 0), ('repeat_index', 'INTEGER', 1, '1', 0), ('passed', 'INTEGER', 1, None, 0), ('seconds', 'REAL', 1, '0', 0), ('peak_kb', 'INTEGER', 1, '0', 0), ('detail', 'TEXT', 1, "''", 0), ('metrics', 'TEXT', 1, "'{}'", 0), ('warnings', 'TEXT', 1, "'[]'", 0), ('failure_class', 'TEXT', 1, "''", 0), ('hit_limit', 'TEXT', 1, "''", 0), ('output', 'TEXT', 0, None, 0), ('artifact_path', 'TEXT', 0, None, 0), ('ttft_s', 'REAL', 0, None, 0), ('first_reasoning_s', 'REAL', 0, None, 0), ('prefill_s', 'REAL', 0, None, 0), ('cold', 'INTEGER', 0, None, 0)]
  index ix_results_cand unique=0 ['candidate_id']
  index ix_results_run unique=0 ['run_id']
  (1, 1, 0, 1, 'coder-7b', 'add', 1, 1, 2.5, 524288, '', '{}', '[]', '', '', 'def add(a, b):/n    return a + b/n', None, None, None, None, None)
  (2, 1, 1, 1, 'coder-7b', 'sort', 1, 1, 2.5, 524288, '', '{}', '[]', '', '', 'def add(a, b):/n    return a + b/n', None, None, None, None, None)
  (3, 1, 2, 1, 'coder-7b', 'parse', 1, 0, 2.5, 524288, 'failed: wrong answer', '{}', '[]', 'content_failed', '', None, None, None, None, None, None)
  (4, 1, 3, 2, 'local-mid', 'add', 1, 1, 2.5, 524288, '', '{}', '[]', '', '', 'def add(a, b):/n    return a + b/n', None, None, None, None, None)
  (5, 1, 4, 2, 'local-mid', 'sort', 1, 0, 2.5, 524288, 'failed: wrong answer', '{}', '[]', 'content_failed', '', 'def add(a, b):/n    return a + b/n', None, None, None, None, None)
  (6, 1, 5, 2, 'local-mid', 'parse', 1, 0, 2.5, 524288, 'failed: wrong answer', '{}', '[]', 'content_failed', '', None, None, None, None, None, None)
  (7, 2, 0, 3, 'image-gen', 'cat', 1, 1, 2.5, 524288, '', '{}', '[]', '', '', None, '/RUNS/0002-image/image-gen-cat.png', None, None, None, None)
  (8, 2, 1, 3, 'image-gen', 'dog', 1, 1, 2.5, 524288, '', '{}', '[]', '', '', None, '/RUNS/0002-image/image-gen-dog.png', None, None, None, None)
  (9, 2, 2, 4, 'screen-broke', 'cat', 1, 0, 2.5, 524288, 'failed: wrong answer', '{}', '[]', 'content_failed', '', None, None, None, None, None, None)
  (10, 2, 3, 4, 'screen-broke', 'dog', 1, 0, 2.5, 524288, 'failed: wrong answer', '{}', '[]', 'content_failed', '', None, None, None, None, None, None)
  (11, 3, 0, 5, 'tts-model', 'hello#1', 1, 1, 2.5, 524288, '', '{}', '[]', '', '', None, '/RUNS/0003-tts/tts-model-hello.wav', None, None, None, None)
  (12, 3, 1, 5, 'tts-model', 'hello#2', 2, 0, 2.5, 524288, 'failed: wrong answer', '{}', '[]', 'content_failed', '', None, '/RUNS/0003-tts/tts-model-hello-2.wav', None, None, None, None)
  (13, 3, 2, 6, 'kokoro', 'hello#1', 1, 1, 2.5, 524288, '', '{}', '[]', '', '', None, '/RUNS/0003-tts/kokoro-hello.wav', None, None, None, None)
  (14, 3, 3, 6, 'kokoro', 'hello#2', 2, 1, 2.5, 524288, '', '{}', '[]', '', '', None, '/RUNS/0003-tts/kokoro-hello-2.wav', None, None, None, None)
table reverifications [('id', 'INTEGER', 0, None, 1), ('lane', 'TEXT', 1, None, 0), ('candidate_id', 'INTEGER', 0, None, 0), ('spec', 'TEXT', 1, None, 0), ('incumbent', 'TEXT', 1, "''", 0), ('triggers', 'TEXT', 1, "'[]'", 0), ('job_id', 'INTEGER', 0, None, 0), ('baseline_run_id', 'INTEGER', 0, None, 0), ('run_id', 'INTEGER', 0, None, 0), ('machine_id', 'INTEGER', 0, None, 0), ('queued_at', 'REAL', 1, None, 0), ('settled_at', 'REAL', 0, None, 0), ('outcome', 'TEXT', 1, "''", 0), ('reason', 'TEXT', 1, "''", 0), ('failure_class', 'TEXT', 1, "''", 0), ('detail', 'TEXT', 1, "''", 0)]
  index ix_reverify_lane unique=0 ['lane', 'candidate_id']
table runs [('id', 'INTEGER', 0, None, 1), ('path', 'TEXT', 1, None, 0), ('lane', 'TEXT', 1, "''", 0), ('tier', 'TEXT', 1, "'measure'", 0), ('machine_id', 'INTEGER', 0, None, 0), ('generated_at', 'REAL', 0, None, 0), ('repeat_count', 'INTEGER', 1, '1', 0), ('cases_digest', 'TEXT', 1, "''", 0), ('receipt', 'TEXT', 1, "'{}'", 0), ('environment', 'TEXT', 1, "'{}'", 0), ('specs', 'TEXT', 1, "'{}'", 0), ('recorded_at', 'REAL', 1, None, 0), ('job_id', 'INTEGER', 0, None, 0), ('split', 'TEXT', 1, "''", 0), ('split_version', 'TEXT', 1, "''", 0)]
  index ix_runs_job unique=0 ['job_id']
  index ix_runs_lane unique=0 ['lane', 'generated_at']
  index sqlite_autoindex_runs_1 unique=1 ['path']
  (1, '20260910-120000-0001-code', 'code', 'screen', 1, 1789032000.0, 1, 'digest-0', '{"modality": "code", "tier": "screen", "cases_digest": "digest-0"}', '{"hw_model": "Mac14,12", "os": "macOS-26.0-arm64-arm-64bit", "arch": "arm64"}', '{"coder-7b": "llamacpp:coder-7b-Q4_K_M", "local-mid": "local-mid"}', 1789032000.0, None, '', '')
  (2, '20260912-090000-0002-image', 'image', 'screen', 1, 1789140000.0, 1, 'digest-1', '{"modality": "image", "tier": "screen", "cases_digest": "digest-1"}', '{"hw_model": "Mac14,12", "os": "", "arch": "arm64"}', '{"image-gen": "mflux:org-m/image-gen", "screen-broke": "diffusers:org-f/screen-broke"}', 1789140000.0, None, '', '')
  (3, '20260920-100000-0003-tts', 'tts', 'measure', 4, 1789788000.0, 1, 'digest-2', '{"modality": "tts", "tier": "measure", "cases_digest": "digest-2"}', '{"hw_model": "Mac17,15", "os": "macOS-27.0.1-arm64-arm-64bit", "arch": "arm64"}', '{"tts-model": "mlx:org-h/tts-model", "kokoro": "kokoro"}', 1789788000.0, None, '', '')
table sightings [('id', 'INTEGER', 0, None, 1), ('proposal_id', 'INTEGER', 1, None, 0), ('source', 'TEXT', 1, None, 0), ('url', 'TEXT', 1, "''", 0), ('why', 'TEXT', 1, "''", 0), ('relevance', 'INTEGER', 1, '0', 0), ('seen_at', 'REAL', 1, None, 0), ('machine_id', 'INTEGER', 0, None, 0)]
  index ix_sight_prop unique=0 ['proposal_id']
  index sqlite_autoindex_sightings_1 unique=1 ['proposal_id', 'source', 'url']
  (1, 1, 'hf-trending', 'https://example.org/org-a/coder-7b-GGUF', 'trending this week', 2, 1788600000.0, 1)
  (2, 2, 'hf-trending', 'https://example.org/org-b/huge-70b', 'trending this week', 2, 1788603600.0, 1)
  (3, 3, 'github-search', 'https://example.org/org-c/old-repo', 'trending this week', 2, 1788607200.0, 1)
  (4, 4, 'hf-trending', 'https://example.org/org-d/lora-x', 'trending this week', 2, 1788610800.0, None)
  (5, 5, 'hf-trending', 'https://example.org/org-e/vllm-only', 'trending this week', 2, 1788614400.0, None)
  (6, 6, 'hf-trending', 'https://example.org/org-f/screen-broke', 'trending this week', 2, 1788618000.0, None)
  (7, 7, 'hf-trending', 'https://example.org/org-g/gguf-llama', 'trending this week', 2, 1788621600.0, None)
  (8, 8, 'hf-trending', 'https://example.org/org-h/tts-model', 'trending this week', 2, 1788625200.0, None)
  (9, 9, 'hf-trending', 'https://example.org/org-i/queued-only', 'trending this week', 2, 1788628800.0, None)
  (10, 10, 'github-search', 'https://example.org/org-j/never-judged', 'trending this week', 2, 1788632400.0, None)
  (11, 11, 'hf-trending', 'https://example.org/org-k/harness-broke', 'trending this week', 2, 1788636000.0, None)
  (12, 12, 'hf-trending', 'https://example.org/org-l/svg-thing', 'trending this week', 2, 1788639600.0, None)
  (13, 13, 'hf-trending', 'https://example.org/org-m/image-gen', 'trending this week', 2, 1788643200.0, None)
table sources [('id', 'INTEGER', 0, None, 1), ('name', 'TEXT', 1, None, 0), ('kind', 'TEXT', 1, "''", 0), ('url', 'TEXT', 1, "''", 0), ('enabled', 'INTEGER', 1, '1', 0), ('last_read_at', 'REAL', 0, None, 0), ('last_attempt_at', 'REAL', 0, None, 0), ('last_status', 'TEXT', 1, "''", 0), ('last_error', 'TEXT', 1, "''", 0), ('failures', 'INTEGER', 1, '0', 0)]
  index sqlite_autoindex_sources_1 unique=1 ['name']
  (1, 'hf-trending', '', '', 1, 1790004000.0, 1790004000.0, 'ok', '', 0)
  (2, 'github-search', '', '', 1, 1790007600.0, 1790007600.0, 'ok', '', 0)
table sqlite_sequence [('name', '', 0, None, 0), ('seq', '', 0, None, 0)]
  ('jobs', 2)
table verdicts [('id', 'INTEGER', 0, None, 1), ('proposal_id', 'INTEGER', 0, None, 0), ('outcome', 'TEXT', 1, None, 0), ('tier', 'TEXT', 1, "''", 0), ('detail', 'TEXT', 1, "''", 0), ('run_path', 'TEXT', 1, "''", 0), ('score', 'REAL', 0, None, 0), ('rubric', 'TEXT', 1, "''", 0), ('judge', 'TEXT', 1, "''", 0), ('decided_at', 'REAL', 1, None, 0), ('machine_id', 'INTEGER', 0, None, 0), ('size_bytes', 'INTEGER', 1, '0', 0), ('upstream_idle_days', 'REAL', 1, '0', 0), ('until', 'TEXT', 1, "''", 0), ('candidate_id', 'INTEGER', 0, None, 0), ('reopens', 'INTEGER', 0, None, 0), ('reopen_kind', 'TEXT', 1, "''", 0), ('run_id', 'INTEGER', 0, None, 0), ('reason', 'TEXT', 1, "''", 0), ('failure_class', 'TEXT', 1, "''", 0), ('split_version', 'TEXT', 1, "''", 0), ('power', 'TEXT', 1, "'{}'", 0)]
  index ix_verdict_cand unique=0 ['candidate_id']
  index ix_verdict_prop unique=0 ['proposal_id']
  (1, 1, 'queued', 'inspect', 'fits: 4.4 GiB of weights under the 23.0 GiB ceiling', '', None, '', '', 1788636000.0, 1, 4724464025, 0.0, '', None, None, '', None, 'candidate', '', '', '{}')
  (2, 1, 'queued', 'judge', 'judged relevant', '', 0.81, 'relevance', 'local-mid', 1788639600.0, 1, 0, 0.0, '', None, None, '', None, 'candidate', '', '', '{}')
  (3, 1, 'queued', 'fetch', 'downloaded', '', None, '', '', 1788643200.0, 1, 0, 0.0, '', None, None, '', None, 'candidate', '', '', '{}')
  (4, 2, 'declined', 'inspect', 'too-big: 39.5 GiB of weights over the 23.0 GiB ceiling', '', None, '', '', 1788646800.0, 1, 42412802048, 0.0, 'ceiling_gb:>39.5', None, None, '', None, 'machine', '', '', '{}')
  (5, 3, 'declined', 'inspect', 'dead: last commit 2.9 years ago', '', None, '', '', 1788650400.0, 1, 0, 1059.0, '', None, None, '', None, 'upstream', '', '', '{}')
  (6, 4, 'ignored', 'inspect', 'attaches to a model: lora in its own card', '', None, '', '', 1788654000.0, 1, 0, 0.0, '', None, None, '', None, 'candidate', '', '', '{}')
  (7, 5, 'queued', 'inspect', 'fits: 14.0 GiB of weights under the 23.0 GiB ceiling', '', None, '', '', 1788657600.0, 1, 0, 0.0, '', None, None, '', None, 'candidate', '', '', '{}')
  (8, 5, 'declined', 'fetch', 'needs-vllm: no vllm on this machine', '', None, '', '', 1788661200.0, 1, 0, 0.0, 'runtime:vllm', None, None, '', None, 'machine', '', '', '{}')
  (9, 7, 'declined', 'inspect', 'needs-llamacpp', '', None, '', '', 1788664800.0, 1, 0, 0.0, 'runtime:llamacpp', None, None, '', None, 'machine', '', '', '{}')
  (10, 8, 'queued', 'inspect', 'fits: 0.3 GiB of weights under the 23.0 GiB ceiling', '', None, '', '', 1788668400.0, 1, 0, 0.0, '', None, None, '', None, 'candidate', '', '', '{}')
  (11, 8, 'queued', 'fetch', 'downloaded', '', None, '', '', 1788672000.0, 1, 0, 0.0, '', None, None, '', None, 'candidate', '', '', '{}')
  (12, 9, 'queued', 'inspect', 'fits: 2.0 GiB of weights under the 23.0 GiB ceiling', '', None, '', '', 1788675600.0, 1, 0, 0.0, '', None, None, '', None, 'candidate', '', '', '{}')
  (13, 1, 'screened', 'screen', 'passed 2/3', 'runs/20260910-120000-0001-code', 0.67, '', '', 1789035600.0, 1, 0, 0.0, '', 1, None, '', 1, 'candidate', '', '', '{}')
  (14, 1, 'measured', 'adopt', 'code: adopted over local-mid at 0.67 vs 0.33', 'runs/20260910-120000-0001-code', 0.67, '', '', 1789039200.0, 1, 0, 0.0, '', 1, None, '', 1, 'candidate', '', '', '{}')
  (15, 13, 'screened', 'screen', 'passed 2/2', 'runs/20260912-090000-0002-image', 1.0, '', '', 1789143600.0, 1, 0, 0.0, '', 3, None, '', 2, 'candidate', '', '', '{}')
  (16, 6, 'broken', 'screen', 'it ran and passed nothing: 0/2', 'runs/20260912-090000-0002-image', 0.0, '', '', 1789147200.0, 1, 0, 0.0, '', 4, None, '', 2, 'candidate', '', '', '{}')
  (17, 11, 'broken', 'screen', 'the screen exited 1: generation thread died', '', None, '', '', 1789176000.0, 1, 0, 0.0, '', None, None, '', None, 'harness', '', '', '{}')
  (18, 11, 'queued', 'inspect', 'retracted: generation thread died is this harness', '', None, '', '', 1789179600.0, 1, 0, 0.0, '', None, 17, 'retraction', None, 'reopened', '', '', '{}')
  (19, 8, 'screened', 'screen', 'passed 1/2', 'runs/20260920-100000-0003-tts', 0.5, '', '', 1789791600.0, 4, 0, 0.0, '', 5, None, '', 3, 'candidate', '', '', '{}')
  (20, 8, 'declined', 'measure', 'lost to the incumbent: 0.50 vs 1.00', 'runs/20260920-100000-0003-tts', 0.5, '', '', 1789795200.0, 4, 0, 0.0, '', 5, None, '', 3, 'candidate', '', '', '{}')
  (21, 12, 'measured', 'adopt', 'svg: preferred by hand over local-large', '', None, '', '', 1789824000.0, 4, 0, 0.0, '', 7, None, '', None, 'candidate', '', '', '{}')
