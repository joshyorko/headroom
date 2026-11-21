# Upstream reconciliation, 2026-10-27

Baseline: `self-hosted` / `9219f615111c98dbc26a0284d3f784ea8b24f99b`.
Upstream: `main` / `17d38e5699b7d7c69ac6addcd762f39e42dd7f00`, release 0.42.0.
The candidate contains all 53 upstream-only commits. Production deployment is separate.

## Decisions

| Area | Decision |
| --- | --- |
| OpenCode | Preserve the fork's session token and default-only bundle export; include upstream environment restoration and malformed-configuration handling. Rebuild the distribution from merged source. |
| Codex learning | Preserve the active instruction limit, full archive, handwritten text and archive-before-active ordering. Use upstream's fence-aware managed-block parser consistently. |
| Read lifecycle | Keep the request-scoped CCR store and explicit hash. If persistence fails, retain the original read instead of emitting an unrecoverable marker. |
| Copilot | Accept native inline OAuth identity and real forwarder regressions; preserve downstream routing regressions. |
| OpenAI Responses | Apply upstream's undeclared web-search history workaround only when the request actually routes to ChatGPT. Preserve API-key and custom-backend history, bypass, WebSocket and fallback behavior. |
| Authentication | Preserve dashboard Basic login, token-header scrubbing, WebSocket authentication, and trusted-dashboard boundaries. Correct Kamal's token interpolation to match the existing local fix. |
| Packaging and deployment | Accept upstream dependency overrides; retain the fork's single amd64 `runtime-self-hosted` publication, Homebrew dispatch, Kamal accessories, persistent state, `/readyz`, and telemetry-off defaults. |
| Governance | Keep the fork's existing removal of release-please and upstream security workflows. |

## Compatibility and operational changes

- The default proxy compression-result cache now stores compressed tool outputs in a local SQLite database at `workspace_dir()/compression_cache.db`. It survives restarts, uses a local filesystem and owner-only permissions, and is disabled in stateless mode or with `HEADROOM_COMPRESSION_CACHE_DISK=0`. This is a new retention behavior.
- Redis-backed CCR and `/v1/compress` session sharing are optional. Existing single-instance deployments do not require Redis. Redis entries are TTL-bound and can be evicted or lost; configuring sessions to use Redis can also select Redis CCR. Runtime errors can fall back to local sessions, so cross-replica availability is not guaranteed. No production Redis service was added or tested.
- Upstream suppresses proxy-injected memory tools for streamed OpenAI requests because that path does not execute them. With explicit memory `tool` mode, automatic context injection is also disabled, so streamed OpenAI requests receive neither mechanism. This limitation is retained rather than silently violating tool-only mode; the existing Kamal default is `live_zone_tail`.
- Upstream advances the release and dependency security overrides, including Pillow 13 for supported Python versions. The actual self-hosted image and live external Qdrant/Neo4j still need independent qualification.
- The deployed LAN dashboard uses HTTP; browser sign-in credentials are unencrypted in transit. HTTPS is required for transport confidentiality.

## Validation

- Focused proxy, authentication, simulated Redis, dashboard, and memory tests: 952 passed with the prior local native extension.
- The first run of 49 further upstream-changed test files reported 1,430 passed, 48 skipped, and 10 failed. One failure exposed the Codex writer merge regression; nine exercised 0.42 Rust behavior using the older local extension. The affected tests passed after the writer repair and replacing that extension with one built from 0.42 source.
- Final native-extension regression run for learning, log compression, and OpenAI HTTP/WebSocket handling: 167 passed. The additional OpenAI, streaming memory, and project-isolation run passed 242 tests. OpenCode: 58 JavaScript and 108 Python tests passed. The synthetic Kamal token test passed against Ruby dotenv's `overwrite: true` mode.
- A clean Dagger wheel smoke installed the `proxy,code,memory-stack,bedrock` extras and imported the native extension. This smoke preceded the final Codex writer fence guard; the final artifact needs a fresh package/image check.
- No provider credentials, production traffic, live Redis, deployment, or live Codex recovery were exercised by local tests.
