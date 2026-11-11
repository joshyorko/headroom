# Fork-only file deletion inventory

All paths were deleted between shared ancestor 17d38e56 and baseline e634a371. Candidate and upstream are checked independently; no restoration/removal is performed here.

| Path | Candidate | Upstream 3c66c91 | Scope/disposition |
|---|---|---|---|
| .github/CODEOWNERS | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/PULL_REQUEST_TEMPLATE.md | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/act/dry-run.json | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/act/pr-governance-invalid.json | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/act/pr-governance-valid.json | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/act/push-feat.json | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/act/push-merge-pr.json | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/act/release-published.json | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/dependabot.yml | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/scripts/pr-health-labels.py | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/workflows/changelog-guard.yml | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/workflows/codeql-triage.yml | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/workflows/merge-conflicts.yml | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/workflows/pr-health.yml | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/workflows/publish.yml | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/workflows/release-metadata-sync.yml | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/workflows/release-please.yml | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/workflows/security.yml | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .github/workflows/stale.yml | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .release-please-config.json | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| .release-please-manifest.json | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| docs/claude-code-bedrock-headroom.md | absent (baseline deletion retained) | present | documentation removal; parent lane |
| docs/content/docs/ci-cd-flows.mdx | absent (baseline deletion retained) | present | documentation removal; parent lane |
| docs/content/docs/releases.mdx | absent (baseline deletion retained) | present | documentation removal; parent lane |
| scripts/pr-governance.py | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| scripts/tests/test_pr_governance.py | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| scripts/tests/test_pr_health_labels.py | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| scripts/tests/test_pr_health_workflow.py | absent (baseline deletion retained) | present | governance/CI ownership: parent lane; ensure upstream merge does not resurrect deleted publishing/governance |
| tests/e2e_cortex_latency.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/e2e_cortex_mcp.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/e2e_cortex_proxy.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/e2e_cortex_proxy_mcp.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/e2e_cortex_quality.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/test_backends/test_bedrock_botocore_preflight.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/test_evals_cjk_tokenization.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/test_force_kompress_all.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/test_learn/test_claude_config_dir.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/test_local_backend_init_race.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/test_memory/test_embedder_thread_cap.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/test_proxy/test_openai_transport_path_prefix.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/test_proxy_loop_exception_health.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |
| tests/test_stateless_toin.py | absent (baseline deletion retained) | present | baseline test removal retained; coverage gap must not be presented as runtime behavior proof |

## Runtime-related removed tests and remaining boundaries

- Cortex latency/MCP/proxy/proxy-MCP/quality E2E scripts: all five absent. They provide no current live-service or latency acceptance.
- `tests/test_backends/test_bedrock_botocore_preflight.py`: removed preflight coverage, matching baseline LiteLLM preflight removal. Live temporary AWS credential prerequisite remains unverified.
- `tests/test_evals_cjk_tokenization.py`: removed CJK evaluator regression coverage; not native inference acceptance.
- `tests/test_force_kompress_all.py`: removed force-all regression coverage. Candidate Kompress behavior/native runtime remains parent build gate.
- `tests/test_learn/test_claude_config_dir.py`: removed Claude config directory coverage; wrapper/install lane must own current replacement checks.
- `tests/test_local_backend_init_race.py`: removed local backend race coverage; baseline initialization behavior retained. Do not claim removed race test passed.
- `tests/test_memory/test_embedder_thread_cap.py`: removed CPU thread-cap coverage and corresponding baseline functionality. CPU embedding concurrency/resource behavior is not restored or measured.
- `tests/test_proxy/test_openai_transport_path_prefix.py`: removed transport prefix suite; current Codex handler/realtime source tests cover selected paths, not that deleted matrix.
- `tests/test_proxy_loop_exception_health.py`: removed event-loop exception health suite; runtime loop health is unproved.
- `tests/test_stateless_toin.py`: removed TOIN stateless regression coverage; actual turn no-disk tests remain startup blocked.

Total deleted paths: 42. Production Python/Rust source files deleted in this diff: 0. The fork also deletes code within modified files; those are recorded in the runtime preservation checklist F25/F26 and net diff artifacts.

## Code deletions inside surviving files

| Baseline file/symbol | Deleted/reverted behavior | Candidate disposition / gap |
|---|---|---|
| headroom/compression/masks.py::compute_entropy_mask_for_content | Content-level high-entropy word mask removed; UniversalCompressor uses token-level mask | Both modules byte-identical baseline; no claim entropy preservation fixed |
| headroom/compression/universal.py::UniversalCompressor._simple_compress | Space-only fallback separator replaced by newline separator | Baseline retained; JSON-string fallback validity is not newly verified |
| headroom/memory/adapters/embedders.py::_resolve_embed_thread_cap; _resolve_embed_concurrency; _init_cpu_embed_worker | Dedicated bounded CPU embed executor/caps removed | Byte-identical baseline; CPU resource gate remains unverified |
| headroom/memory/backends/local.py::_get_init_lock; _init_locked | LocalBackend singleflight initialization removed | Candidate retains baseline LocalBackend behavior; MemoryHandler lock is separate and must not be conflated |
| headroom/pricing/litellm_pricing.py::_register_minimax_pricing | Fork baseline omits MiniMax registration helper | Candidate continues absence; current model-resolution tests are source-only evidence |
| headroom/proxy/server.py::_is_proxy_token_bearer | Bearer-only scrub helper replaced by _is_proxy_token_authorization | Browser Basic + bearer credential scrub retained; production startup-backed tests still pending |
| crates/headroom-core/src/transforms/unidiff_detector.rs::is_diff | catch_unwind containment and orphaned-target regression test removed | Detector byte-identical baseline; no parser panic behavior claim from this audit |
| headroom/backends/litellm.py::_fetch_bedrock_inference_profiles | Explicit-profile boto3 session/profile cache key reverted to ambient client/region cache | Candidate preserves baseline; explicit-profile discovery/live AWS gate unverified |
| headroom/backends/litellm.py::LiteLLMBackend.__init__ | Temporary-credential botocore availability preflight removed | Baseline retained; dependency/runtime prerequisite not waived |
| headroom/backends/litellm.py::LiteLLMBackend streaming provider kwargs | Selected streaming aws_profile_name forwarding removed by baseline | Must remain a documented baseline limitation; no live AWS proof |
