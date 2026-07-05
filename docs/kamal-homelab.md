# Headroom Kamal Homelab Deploy

Direct VM deployment. No Cloudflare tunnel/accessory.

## Fill host

```bash
cp .env.kamal.local.example .env.kamal.local
$EDITOR .env.kamal.local
```

Set `KAMAL_HOST` and `KAMAL_PUBLIC_HOST` to Harvester VM IP. Keep `KAMAL_PUBLIC_HOST`
as IP unless DNS exists.

## Prepare VM

Kamal needs SSH access plus Docker on VM. From this repo:

```bash
bin/kamal server bootstrap
```

## Boot stateful services

```bash
bin/kamal accessory boot qdrant
bin/kamal accessory boot neo4j
```

Qdrant and Neo4j data live under `KAMAL_STORAGE_PATH` on VM. Default:
`/home/kdlocpanda/headroom-data`, so no root-owned host directory needed.

## Deploy app

```bash
bin/kamal setup
```

For later changes:

```bash
bin/kamal deploy
```

## Calibrate output shaping

`headroom learn --agent codex --verbosity --apply` reads local Codex sessions
from `~/.codex/sessions` and writes learned state under local `~/.headroom`.
The deployed proxy reads the Kamal state volume mounted at
`/home/nonroot/.headroom`, backed by `${KAMAL_STORAGE_PATH}/state` on the VM.

To let the deployed proxy use learned verbosity and output-savings baselines,
leave `HEADROOM_VERBOSITY_LEVEL` unset in `.env.kamal.local`, then sync the
learned files after running the local learner:

```bash
headroom learn --agent codex --verbosity --apply
set -a
. ./.env.kamal.local
set +a
scp ~/.headroom/verbosity.json ~/.headroom/output_savings.json \
  "${KAMAL_SSH_USER}@${KAMAL_HOST}:${KAMAL_STORAGE_PATH}/state/"
bin/kamal app boot
```

Set `HEADROOM_VERBOSITY_LEVEL` only when you want a manual deploy-wide override.
When it is unset, Headroom falls back to the learned `verbosity.json` in the
Kamal state volume.

`bin/kamal app boot` reboots the existing app container so it rereads the synced
state files. For code or deploy-config changes, use `bin/kamal deploy` instead.

## Check

```bash
curl -fsS "http://${KAMAL_PUBLIC_HOST}/readyz"
bin/kamal logs
```

## Current caveat

Kamal runs Qdrant and Neo4j as accessories now, and `config/deploy.yml` starts
the app with `--memory-backend qdrant-neo4j`. Keep `.env.kamal.local` aligned
with that backend and verify both accessories are booted before relying on graph
memory.
