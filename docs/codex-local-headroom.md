# Local Headroom for Codex

## What This Setup Does

This local Docker Compose profile uses Headroom as a Codex proxy on a Linux workstation. It keeps the upstream Compose stack intact and adds local defaults through `compose.override.yml`, `.env`, and `scripts/headroom-local`.

Primary goal: token-mode Codex runs with explicit compression knobs, conservative memory context, and low setup friction. This profile favors headroom over provider prefix-cache stability; switch to `HEADROOM_MODE=cache` when cache behavior matters more than token reduction.

## Safety Defaults

- Publishes Headroom, Qdrant, and Neo4j only on `127.0.0.1`, not the LAN.
- Uses `HEADROOM_MODE=token` by default with `HEADROOM_TARGET_RATIO=0.4`.
- Persists Headroom state in the `headroom_state` named volume.
- Keeps `HEADROOM_LOG_MESSAGES=0` so full prompt/message contents are not saved by default.
- Runs proxy with `--no-learn`; learning writes stay disabled until explicitly enabled.
- Keeps memory scoped with low `HEADROOM_MEMORY_TOP_K`, higher `HEADROOM_MIN_EVIDENCE`, and a short fail-open context timeout.

Do not run `up`, `down`, or `restart` while another agent is actively using the current proxy. These files are prepared now; apply them after the running agent finishes.

## First Run

```bash
scripts/headroom-local up
scripts/headroom-local status
scripts/headroom-local perf
scripts/headroom-local logs
```

`.env` is already created for this local clone.

## Apply After Current Agent Finishes

When the active Codex run is done and it is safe to interrupt the proxy:

```bash
scripts/headroom-local down
scripts/headroom-local up
scripts/headroom-local status
scripts/headroom-local perf
```

This rebuilds and starts the Compose stack with the local override. Named volumes are preserved.

## Daily Commands

```bash
scripts/headroom-local up
scripts/headroom-local status
scripts/headroom-local doctor
scripts/headroom-local perf
scripts/headroom-local logs
scripts/headroom-local restart
scripts/headroom-local down
```

`down` uses `docker compose down`, which stops containers but does not delete named volumes unless `--volumes` is added. Do not add `--volumes` unless you intend to reset persisted state.

## Memory Behavior

Memory is enabled for local Codex context, backed by Qdrant from Docker Compose and a persistent SQLite DB at `/home/nonroot/.headroom/memory.db`.

Default scope:

```bash
HEADROOM_MEMORY_PROJECT_ROOT=/home/nonroot
HEADROOM_MEMORY_TOP_K=5
HEADROOM_MIN_EVIDENCE=10
HEADROOM_MEMORY_CONTEXT_TIMEOUT_SECONDS=1.0
```

This keeps memory retrieval conservative and fail-open. If memory lookup is slow, requests should continue instead of blocking the Codex loop for a long time.

## Why Learn Is Disabled

`--no-learn` is intentional. Current local goal is token-mode compression, observability, and conservative memory context. Learning writes and full message logging are separate opt-ins because they change durability and privacy behavior.

## Inspect Performance

```bash
scripts/headroom-local status
scripts/headroom-local perf
curl --fail --silent http://127.0.0.1:8787/stats | jq .
```

For Codex, read cache metrics separately from token reduction. Token mode should increase compression savings, while cache metrics still show whether provider prefix stays useful.

Useful signs:

- High cache hit rate.
- High cache read tokens compared with cache write tokens.
- Low recent write tokens for repeated Codex turns.
- Low optimization overhead.

Weak signs to watch:

- Low retrieval count after many CCR/TOIN compressions.
- Many requests with optimization overhead above 500 ms.
- Max overhead in seconds instead of milliseconds.
- Aggregate token savings that undersell prefix-cache wins.

## Cache Mode vs Token Mode

```bash
HEADROOM_MODE=cache docker compose up -d --build
HEADROOM_MODE=token docker compose up -d --build
```

Use `cache` for long Codex loops where provider prefix-cache stability matters more than token reduction.

Use `token` for Codex traffic that should still get structural savings and output shaping. This local profile defaults to token mode.

## Codex Latency Profile

The local defaults bias toward lower latency while keeping Codex output shaping enabled:

```bash
HEADROOM_MODE=token
HEADROOM_TARGET_RATIO=0.4
HEADROOM_OUTPUT_SHAPER=1
HEADROOM_VERBOSITY_LEVEL=2
HEADROOM_EFFORT_ROUTER=0
HEADROOM_DISABLE_KOMPRESS=1
HEADROOM_DISABLE_KOMPRESS_FALLBACK=1
HEADROOM_CODE_AWARE_ENABLED=0
HEADROOM_COMPRESS_USER_MESSAGES=0
HEADROOM_MIN_TOKENS=5000
HEADROOM_MEMORY_CONTEXT_TIMEOUT_SECONDS=1.0
HEADROOM_LOG_MESSAGES=0
```

Dashboard `output_shaping.applied_requests` and `latest_label=output_shaper:verbosity:L2` mean Codex steering is active. `Output Tokens Saved: 0` can still be valid until Headroom has a learned baseline or holdout comparison for estimating output-token savings.

If optimization overhead remains high after applying the override, keep the shaper on and inspect compression latency first. Restart after active agents finish so in-flight Codex sessions are not interrupted.

## Reset Local Headroom State

Stop the stack first:

```bash
scripts/headroom-local down
```

Then remove only the Headroom state volume:

```bash
docker volume rm headroom_headroom_state
```

Qdrant and Neo4j use separate named volumes. Leave them alone unless you want to reset vector and graph state too.

## Troubleshooting

Run:

```bash
scripts/headroom-local doctor
scripts/headroom-local check-profile
docker compose config
docker compose ps
```

If `readyz` fails, check:

```bash
scripts/headroom-local logs
```

If `qdrant` fails, check:

```bash
curl --fail --silent http://127.0.0.1:6333/collections | jq .
```

If Neo4j fails, verify the Bolt port:

```bash
timeout 2 bash -c 'cat < /dev/null > /dev/tcp/127.0.0.1/7687'
```
