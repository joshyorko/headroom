# Selective upstream reconciliation ledger

Baseline: downstream `self-hosted` / `ad7eea0d310c13278965a54488dbb6a9e3162d33`.
Upstream inventory: `upstream/main` / `6d2254dfb5eb97f92249e0ee7aa04b2697adfa69`.
The inventory contains 54 upstream-only commits. No upstream merge is used.

| Upstream commit | Decision | Reason |
| --- | --- | --- |
| `6d2254df` | accepted | Preserve Anthropic 1M-context pricing behavior. |
| `b3f44363` | adapted | Import signed-thinking wire accounting while retaining downstream streaming hooks. |
| `942af56f` | superseded | Empty replay of the retained retrieval-history repair. |
| `1b0b0b89` | superseded | Empty replay of the retained savings-attribution group. |
| `cbb950a4` | excluded | Upstream governance-only CI policy. |
| `ac8646aa` | excluded | Upstream release-credential automation. |
| `481e0b83` | accepted | Loopback-only Compose publication preserves the self-hosted boundary. |
| `a6ab359a` | accepted | Add loopback write CSRF protection without changing trusted-LAN routing. |
| `96c25f51` | excluded | macOS-only allocator behavior. |
| `ef7e07e0` | adapted | Add one-hour cache-write net-cost pricing while retaining local model aliases. |
| `2a847252` | accepted | Make the Claude 1M fallback configurable. |
| `ddd9f767` | excluded | Windows-only installer cleanup. |
| `c8310819` | accepted | Set the xAI upstream for Grok Build routing. |
| `6d87825f` | excluded | macOS-only allocator tuning. |
| `be5b26d8` | accepted | Surface Claude Desktop proxy bypasses in doctor output. |
| `536c949a` | adapted | Propagate Responses usage without removing downstream accounting. |
| `a06a51ec` | adapted | Preserve Codex WebSocket model attribution. |
| `a01897c7` | adapted | Guard Gemini continuation usage against null values. |
| `9d370592` | adapted | Replay cached responses without the producing turn wire framing. |
| `f9807fd6` | adapted | Add extension attribution while retaining RTK project and lifetime totals. |
| `2f4d001c` | accepted | Keep prefixed core tools resident. |
| `322425c4` | excluded | Dependency-only change without a retained runtime requirement. |
| `5731be7e` | excluded | Dependency-only change without a retained runtime requirement. |
| `ff17961c` | excluded | Dependency-only change without a retained runtime requirement. |
| `bbe90131` | excluded | Dependency-only change without a retained runtime requirement. |
| `888a9f4e` | excluded | Dependency-only change without a retained runtime requirement. |
| `2d88e31a` | accepted | Reject conflicting Claude auth before proxy startup. |
| `aa811fa9` | excluded | CI governance for generated dependency commits. |
| `7e312805` | excluded | CI governance for Dependabot commits. |
| `8ea87e78` | adapted | Resolve deferred tool-search results without breaking downstream tool logging. |
| `8a1d38bc` | adapted | Complete stateless Responses and buffered CCR lifecycle handling. |
| `a708c057` | excluded | Upstream test-sharding CI workaround. |
| `31452426` | adapted | Unify savings attribution while preserving downstream persistence and dashboard fields. |
| `1aa701ad` | adapted | Preserve compatible Claude modes and durable Copilot CAPI routing. |
| `eafdf11a` | adapted | Add Bedrock packaging support while retaining the self-hosted registry and deployment shape. |
| `ddd2a259` | excluded | Windows-only installer behavior. |
| `a3fe5cb6` | accepted | Enforce Rust ONNX API-24 compatibility. |
| `7de35739` | adapted | Repair Anthropic retrieval history with project-scoped downstream behavior intact. |
| `6077e5a1` | accepted | Restore MCP SDK v1 compatibility. |
| `b7f342c1` | accepted | Preflight proxy dependencies before mutating Codex configuration. |
| `9fde1275` | adapted | Relocate stray system messages while preserving provider routing. |
| `6576ef63` | accepted | Add OpenClaw timeout and circuit-breaker safety. |
| `82526191` | accepted | Resolve deployment profiles during install. |
| `f1c34d33` | adapted | Avoid buffering Anthropic CCR passthrough streams. |
| `2d1e96b8` | adapted | Sanitize memory entity references while retaining external backends and project scope. |
| `6147883d` | accepted | Prevent Serena pre-indexing from blocking launch. |
| `41dab2d0` | adapted | Verify CCR marker hashes before advertisement. |
| `d76fce04` | adapted | Adapt buffered Responses SSE while retaining byte-faithful downstream paths. |
| `d6d121e3` | adapted | Repair retrieval history across sessionless and provider-specific paths. |
| `b30f339d` | excluded | Dependency-only Criterion update without a retained runtime requirement. |

Accepted/adapted commits are applied as dependency-complete groups below; excluded
and superseded commits are intentionally absent from the resulting history.
