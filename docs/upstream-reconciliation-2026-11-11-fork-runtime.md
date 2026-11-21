# Downstream runtime preservation checklist

Final native qualification supersedes the initial missing-core receipts below; see [the main ledger](upstream-reconciliation-2026-11-11.md#final-native-qualification). Temporary named logs/diffs were used during this audit and are cleaned at handoff; the behavior/source/test mapping is retained here.

Baseline: e634a371. Shared ancestor used for net inventory: 17d38e56. Upstream: 3c66c91. Candidate: current shared worktree; regenerate checks after further edits.

This separates retained source from execution. No full acceptance claim: native extension is absent in this interpreter, so startup-backed routes remain blocked. No deployment/provider calls were made.

## Behavior inventory

| ID | Downstream behavior | Baseline/current location | Preservation review | Test location | Result / gap |
|---|---|---|---|---|---|
| F01 | Hermes/OpenRouter explicit model backend and incoming credential scrub | headroom/proxy/handlers/openai.py::_select_openai_chat_backend; _openai_chat_backend_headers | All baseline routing branches retained; candidate adds upstream forward-path/admission flow | test_proxy/test_openai_backend_path.py::test_openrouter_model_prefix_uses_openrouter_backend | SOURCE RETAINED; endpoint proof blocked by missing core |
| F02 | Hermes OpenRouter catalog list/detail, prefixed IDs, server-side catalog credential | headroom/providers/model_metadata.py::_handle_openrouter_model_metadata | All fork catalog functions retained; upstream HTTP/1 Codex client addition leaves catalog path intact | test_provider_proxy_routes.py::test_v1_models_fetches_openrouter_catalog_for_hermes_client_prefix | SOURCE RETAINED; startup blocked |
| F03 | Opaque realtime POST/WebRTC and websocket voice routes, auth/origin handling | headroom/providers/openai_realtime.py::handle_realtime_call; relay_realtime_websocket; headroom/providers/proxy_routes.py::register_provider_routes | Realtime module byte-identical to baseline; route registrations retained | test_provider_openai_realtime.py | 11 direct tests passed; 5 route tests startup blocked |
| F04 | Codex explicit ChatGPT account/auth detection and configured realtime upstream | headroom/providers/codex/runtime.py::resolve_codex_routing; headroom/providers/codex/install.py | runtime byte-identical; installer fork additions retained alongside upstream config support | test_openai_codex_routing.py; test_provider_openai_realtime.py | 55 Codex handler tests passed; real provider/native unproved |
| F05 | Client/project/Copilot URL prefixes and safe plan-host selection | headroom/proxy/project_context.py::strip_client_path_prefix; strip_copilot_upstream_path_prefix; with_copilot_upstream_prefix | Entire module byte-identical to baseline; server prefix strip order remains client then project then Copilot | test_proxy_copilot_auth_downstream.py; test_provider_proxy_routes.py::test_client_and_project_prefixes_reach_openai_chat_handler | 3 downstream Copilot tests passed; endpoint startup blocked |
| F06 | Copilot token refresh/routing headers and metadata fallback | headroom/providers/copilot/wrap.py::build_launch_env; headroom/proxy/handlers/openai.py::handle_passthrough | Copilot wrap/export modules byte-identical; token-shape based metadata upstream fallback retained | test_proxy_copilot_auth_downstream.py | PASS source; live token refresh unproved |
| F07 | Explicit x-client precedence, internal x-headroom-client fallback, UA attribution | headroom/proxy/auth_policy.py::classify_client_signals; headroom/proxy/auth_mode.py::_auth_signals | Fork signal field and precedence retained; auth_mode module byte-identical | test_auth_mode.py; test_dashboard_agent_usage.py | PASS source |
| F08 | Bearer token classification in Rust and Python | crates/headroom-core/src/auth_mode.rs::classify; headroom/proxy/auth_policy.py::classify_auth_signals | Upstream broad sk-ant-oat prefix accepts baseline dashed tokens plus actual oat01 tokens; case-insensitive schemes and extra spaces retained. Python already used broad prefix on baseline | test_auth_mode.py; crates/headroom-core/src/auth_mode.rs::tests | 24 Python cases passed; Rust execution pending |
| F09 | Local/Qdrant-Neo4j backend selection and per-project composite user IDs | headroom/proxy/memory_handler.py::__init__; _resolve_for_request; headroom/proxy/models.py::ProxyConfig; headroom/settings_store.py::SETTINGS | Backend config/settings retained; router construction moved earlier by upstream to fail closed before initialization, replacing duplicated Qdrant construction | test_memory_storage_router.py; test_memory_handler_project_isolation.py; test_memory_handler_native_ops.py | PASS source; external Qdrant/Neo4j unproved |
| F10 | Concurrent local backend initialization and relation-key compatibility | headroom/memory/backends/local.py::_ensure_initialized | MemoryHandler retains its initialization lock; LocalBackend itself has no initialization singleflight on the baseline or candidate (baseline removed _get_init_lock/_init_locked). Only candidate LocalBackend change accepts relation as alias for type | test_memory_handler_project_isolation.py; test_memory/test_entity_ref_sanitization.py | PASS source; embedding runtime not exercised |
| F11 | Learner per-user/per-backend evidence, queue targets, scoped LRU eviction | headroom/memory/traffic_learner.py::_dedup_hash; _accumulate; _save_pattern | Scoped keys and targets carried through upstream retry/cancellation/idempotency pipeline; scoped backend used for writes and index refresh | test_memory/test_traffic_learner.py::test_same_pattern_persists_per_request_user_scope; test_scoped_lru_eviction_preserves_targets_and_persistence_scope | PASS source |
| F12 | Scoped evidence excluded from default sidecar; uncertain saves reconcile after restart | headroom/memory/traffic_learner.py::_save_pending_state; _load_pending_state; _find_persisted_pattern | Scope exclusion retained; upstream save tokens and queued evidence snapshots integrated; first evidence threshold semantics follow upstream | test_memory/test_traffic_learner.py::test_request_scope_is_not_written_to_default_sidecar | PASS source |
| F13 | OpenAI HTTP/WS learner ingestion and scoped-Codex learning guard | headroom/proxy/handlers/openai.py::_observe_openai_responses_traffic; _observe_openai_ws_response_create | Fork request user/backend args retained with upstream unresolved-project guard; original scoped Codex suppression retained | test_openai_responses_traffic_learner.py; test_openai_traffic_learning.py | Responses learner suite passed; dedicated traffic-learning file not rerun this audit |
| F14 | Modern and legacy memory execution signatures on Responses continuations | headroom/proxy/handlers/openai.py::handle_openai_responses | Canonical method receives request_context directly. Legacy adapters require a resolver for contextual requests; distinct physical backend targets fail closed, same-backend targets receive effective composite user_id; unscoped calls keep their user_id. No shared backend mutation | test_openai_codex_routing.py::test_openai_responses_memory_continuation_is_zdr_safe | 24 scoped/legacy mocked continuation variants passed; 10 actual handler/resolver + real SQLite store tests passed. Legacy adapter is test-only, not an actual historical implementation |
| F15 | Only ChatGPT-auth Responses/WS drop undeclared web-search history; custom APIs preserve it | headroom/proxy/handlers/openai.py::handle_openai_responses; handle_openai_responses_ws | Fork auth-scoped cleanup retained on HTTP and every outgoing WS frame | test_openai_responses_web_search_history.py | PASS source |
| F16 | Output savings reliability metadata and honest modelled estimates | headroom/proxy/output_savings.py::SavingsEstimate; SavingsLedger._estimate_status; headroom/proxy/server.py::_output_reduction_payload | All fork status/reasons/quality/display gates retained alongside upstream file locking/migration | test_output_savings.py; test_stats_output_reduction_gate.py | Savings tests and 6 direct gates passed; 6 /stats startup cases blocked |
| F17 | Dashboard output headline and steering fallback; provider cache discount separated | headroom/dashboard/templates/dashboard.html:315 | All fork executable template additions retained; reliable display values gate numeric headline | test_dashboard_agent_usage.py; test_stats_output_reduction_gate.py | Source checks passed; rendered browser/native startup unproved |
| F18 | Browser Basic sign-in restricted to dashboard/settings/data routes; proxy credential scrub | headroom/proxy/server.py::_dashboard_basic_token; _is_dashboard_browser_request; scrub_proxy_token_headers | All baseline auth functions/allowlists retained; upstream auth rejection redaction and stats-metadata widening added | test_dashboard_browser_auth.py | SOURCE RETAINED; all 30 startup cases blocked |
| F19 | Trusted LAN settings reads/writes, same-origin protection, guarded local mutation endpoints | headroom/proxy/server.py::_require_loopback_or_trusted_dashboard_client; _require_same_origin_or_trusted_dashboard_client | Fork trusted-CIDR path retained with guard ordering; upstream stats metadata access does not replace settings guard | test_proxy_loopback_gating.py | PASS direct guard/source tests; full dashboard startup unproved |
| F20 | Project attribution and durable savings/lifetime accounting | headroom/proxy/savings_tracker.py::_record_project_locked; lifetime_response; headroom/proxy/project_context.py::classify_project_from_payload | Project context byte-identical; tracker retains normal project counters; upstream provider/tool ledger improvements auto-merge | test_proxy_project_savings.py; test_dashboard_agent_usage.py | 146 inherited tests passed as batch; 5 project endpoint cases blocked |
| F21 | Process stateless flag and no workspace persistence | headroom/paths.py::set_process_stateless; process_is_stateless; headroom/proxy/output_savings.py::SavingsRecorder._flush_locked; headroom/proxy/audit.py::record_admin_action | paths/audit/debug-dump byte-identical; recorder and migration return before lock/file creation in stateless mode; registry in-memory cache option retained | test_stateless_no_disk.py; test_provider_registry_extended.py | 13 stateless/direct cases passed; 2 actual turn cases startup blocked |
| F22 | Semantic cache distinguishes shaping-relevant request fields and rejects non-cacheable replies | headroom/proxy/semantic_cache.py::SemanticCache._compute_key; _is_cacheable_reply | Entire module byte-identical to baseline | test_semantic_cache_key_policy.py | 6 source tests passed |
| F23 | CCR marker validation, entity reference sanitation, retrieval-history repair, resident core tools | headroom/ccr/tool_injection.py::CCRToolInjector; headroom/memory/models.py::normalize_entity_refs; headroom/proxy/helpers.py::strip_unsupported_ccr_retrieve_blocks | Historical reconciliations converged with upstream before baseline; candidate retains guards and expands resident tool names | test_ccr_retrieve_history_repair.py; test_ccr_tool_always_on.py; test_ccr_tool_injection.py; test_memory/test_entity_ref_sanitization.py | PASS inherited source batch |
| F24 | Signed-thinking/byte-faithful forwarding and WS memory relay lifecycle | headroom/proxy/body_forwarding.py::select_outbound_body; headroom/proxy/handlers/openai.py::handle_openai_responses_ws | Body-forwarding module byte-identical to baseline; upstream response framing and HTTP/1 routing integrated | test_ws_memory_relay.py; test_openai_codex_routing.py | PASS source; full signed-thinking matrix not rerun |
| F25 | Baseline compressor decisions: entropy token mask, newline fallback, stateless TOIN behavior | headroom/compression/masks.py; headroom/compression/universal.py::UniversalCompressor; headroom/transforms/compression_units.py::compress_unit_with_router; headroom/transforms/lossless_compaction.py | masks/universal byte-identical; baseline removals relative merge-base remain removals (not resurrected); compression unit additions remain; lossless compaction gets upstream stricter path-only folding | test_compression_units.py | PASS source; entropy preservation behavior not claimed corrected |
| F26 | Rust detector behavior and native build linkage policy | crates/headroom-core/src/transforms/unidiff_detector.rs::is_diff; crates/headroom-core/src/transforms/detection.rs; crates/headroom-py/build.rs | Diff detector/detection/build script byte-identical to baseline; upstream Magika adds telemetry default-off and excludes implicit untrusted cwd discovery; lru upgraded 0.12->0.19 | crates/headroom-core/tests/auth_mode.rs; native build/test gate | SOURCE RETAINED; Rust/native tests pending parent build |
| F27 | Pricing/model alias normalization and Bedrock ARN converse routing | headroom/pricing/litellm_model_resolution.py::unwrapped_model_forms; headroom/backends/litellm.py::LiteLLMBackend; headroom/providers/registry.py::create_proxy_backend | Model resolution byte-identical; all fork model mapping additions retained; upstream litellm changes are not live provider acceptance | test_pricing_litellm.py; test_provider_registry_extended.py | PASS source; Bedrock profile/live provider behavior unproved |

## Complete net file inventory

The inventory includes executable additions and deletions relative to 17d38e56, including auto-merges. Exact line retention is supporting evidence, not proof of semantic equivalence.

| File | Candidate vs baseline | Added executable lines retained | Review disposition |
|---|---|---|---|
| crates/headroom-core/src/auth_mode.rs | changed | 0/1 exact lines | upstream prefix broadens accepted tokens; preserves dashed baseline tokens |
| crates/headroom-core/src/transforms/detection.rs | byte-identical | 0/0 exact lines | retained |
| crates/headroom-core/src/transforms/magika_detector.rs | changed | 0/0 exact lines | retained |
| crates/headroom-core/src/transforms/unidiff_detector.rs | byte-identical | 5/5 exact lines | retained |
| crates/headroom-core/tests/auth_mode.rs | byte-identical | 0/0 exact lines | retained |
| crates/headroom-proxy/Cargo.toml | changed | 0/1 exact lines | upstream lru soundness update to 0.19 |
| crates/headroom-py/build.rs | byte-identical | 23/23 exact lines | retained |
| headroom/cache/backends/__init__.py | byte-identical | 0/0 exact lines | retained |
| headroom/cache/backends/sqlite.py | changed | 3/3 exact lines | retained |
| headroom/compression/masks.py | byte-identical | 0/0 exact lines | retained |
| headroom/compression/universal.py | byte-identical | 4/4 exact lines | retained |
| headroom/dashboard/templates/dashboard.html | changed | 28/28 exact lines | retained |
| headroom/memory/adapters/embedders.py | byte-identical | 0/0 exact lines | retained |
| headroom/memory/backends/local.py | changed | 42/42 exact lines | retained |
| headroom/memory/traffic_learner.py | changed | 79/110 exact lines | scoped persistence integrated with upstream retry pipeline (F11/F12) |
| headroom/offline.py | byte-identical | 1/1 exact lines | retained |
| headroom/paths.py | byte-identical | 2/2 exact lines | retained |
| headroom/pricing/litellm_model_resolution.py | byte-identical | 42/42 exact lines | retained |
| headroom/pricing/litellm_pricing.py | changed | 2/2 exact lines | retained |
| headroom/providers/codex/images.py | byte-identical | 0/0 exact lines | retained |
| headroom/providers/codex/install.py | changed | 21/21 exact lines | retained |
| headroom/providers/codex/runtime.py | byte-identical | 9/9 exact lines | retained |
| headroom/providers/copilot/__init__.py | byte-identical | 2/2 exact lines | retained |
| headroom/providers/copilot/wrap.py | byte-identical | 20/20 exact lines | retained |
| headroom/providers/model_metadata.py | changed | 132/132 exact lines | retained |
| headroom/providers/openai.py | changed | 2/2 exact lines | retained |
| headroom/providers/openai_realtime.py | byte-identical | 207/207 exact lines | retained |
| headroom/providers/opencode/config.py | byte-identical | 1/1 exact lines | retained |
| headroom/providers/opencode/install.py | byte-identical | 2/2 exact lines | retained |
| headroom/providers/proxy_routes.py | changed | 62/62 exact lines | retained |
| headroom/providers/registry.py | changed | 4/4 exact lines | retained |
| headroom/proxy/audit.py | byte-identical | 3/3 exact lines | retained |
| headroom/proxy/auth_mode.py | byte-identical | 8/8 exact lines | retained |
| headroom/proxy/auth_policy.py | changed | 4/4 exact lines | retained |
| headroom/proxy/handlers/_debug_dump.py | byte-identical | 3/3 exact lines | retained |
| headroom/proxy/handlers/openai.py | changed | 117/117 exact lines | retained |
| headroom/proxy/memory_handler.py | changed | 5/12 exact lines | same router config constructed before backend init (F09) |
| headroom/proxy/models.py | changed | 1/1 exact lines | retained |
| headroom/proxy/output_savings.py | changed | 49/49 exact lines | retained |
| headroom/proxy/project_context.py | byte-identical | 145/145 exact lines | retained |
| headroom/proxy/server.py | changed | 89/89 exact lines | retained |
| headroom/settings_store.py | changed | 42/42 exact lines | retained |
| headroom/transforms/compression_units.py | changed | 6/6 exact lines | retained |
| headroom/transforms/lossless_compaction.py | changed | 10/10 exact lines | retained |

## Historical changes no longer present on the baseline

- RTK remote reports and per-project RTK lifetime snapshots from e497b737/ad78b73e are absent in e634a371, 17d38e56, upstream and candidate: `report_context_tool_stats`, `ingest_context_tool_stats`, `_get_context_tool_reported_project_stats`, `upsert_context_tool_project_snapshot`. This is historical baseline absence, not a removal by this merge. Do not restore without explicit scope. `docs/content/docs/configuration.mdx:24` still mentions RTK gain scope, which current runtime does not read.
- Old settings helpers `_require_settings_access` / `_require_settings_same_origin` were renamed/replaced before the baseline; current trusted-CIDR and same-origin helpers are retained (F19).
- Old inline OpenRouter catalog helpers moved to `headroom/providers/model_metadata.py` before baseline; behavior retained there (F02).
- Old inline shaping helpers moved to `headroom/proxy/output_shaper.py` and current shared shaping calls before baseline; module is byte-identical. Historical function-name disappearance is not a new merge deletion.
- Historical `_set_project_from_payload_if_missing` / `_observe_traffic_for_learning` helpers are absent on baseline. Current prefix/header attribution and handler-specific learning are retained; do not claim automatic payload attribution solely because `classify_project_from_payload` exists.

## Verification receipts

- `proxy-merge-tests.log`: 304 passed, 4 failed at missing-core startup; learner/project isolation/native memory source checks passed.
- `proxy-routing-tests.log`: 50 passed, 6 failed and 13 errors at missing-core startup.
- `fork-acceptance-tests.log`: 446 passed, 44 failed and 30 errors. Every nonpass diagnostic points to missing `headroom._core` startup. Includes both scoped and legacy memory continuation signatures.
- `fork-inherited-tests.log`: 146 passed, 5 project endpoint failures at missing-core startup.
- Ruff passes for final changed handler/test files. No native build or external-service acceptance performed by this audit.

## Legacy dispatch contract and isolation proof

- Repository and sampled refs 66a72e57/e497b737/17d38e56/e634a371 contain only canonical `_execute_memory_tool(..., *, request_context=None)`. No production legacy-signature implementation was found.
- `tests/test_responses_memory_dispatch_isolation.py` uses actual MemoryHandler save/search methods, actual BackendRouter scope resolution and actual SQLiteMemoryStore CRUD/filtering. Only the backend protocol bridge and old-signature adapter are test-owned. This does not qualify live Qdrant, Neo4j, vector indexes or embedding.
- Canonical local GLOBAL/USER/PROJECT and Qdrant-style composite partitions preserve users/projects in persisted SQLite rows. Legacy local GLOBAL and same-backend composite IDs work; legacy distinct local USER/PROJECT targets return `legacy_request_scope_unsupported` without saving. Missing resolver contextual calls also skip. Unresolved project remains skipped.
- No shared backend is swapped. Caller sees explicit skipped reason rather than falling through to default storage.
- Final dispatch isolation result: `memory-dispatch-isolation-final.log` has 10 passed. A process-only mutation restoring the prior raw-user legacy fallback makes the local-project legacy test fail (expected negative receipt: `memory-dispatch-before-negative.log`); production files were not changed for that check. Initial 4 fixture failures were absent parent directories in the test bridge and were corrected; no production failure was hidden. Codex routing suite had 55 passes after helper extraction (initial combined test receipt).
- Complete deletion inventory: `fork-runtime-deletions-checklist.md` (42 files; all still absent).

## Supporting artifacts

- `fork-runtime-baseline.diff`: complete net Python/Rust runtime diff 17d38e56..e634a371.
- `fork-runtime-candidate.diff`: initial candidate vs baseline capture; handler signature restoration happened after capture, so use live diff for final review.
- `fork-runtime-vs-upstream.diff`: initial downstream candidate vs upstream capture.
- `fork-runtime-history.txt`: first-parent downstream change inventory.
- `fork-runtime-line-audit.json`: refreshed exact executable-line retention for all net scoped files.
- `fork-historical-missing-symbols.json`: historical added-symbol absences, including baseline absences; names alone do not establish lost behavior.
