# Headroom Kamal Homelab Deploy

Direct VM deployment. No Cloudflare tunnel/accessory.

## Fill host

```bash
cp .env.kamal.local.example .env.kamal.local
$EDITOR .env.kamal.local
```

Set `KAMAL_HOST` and `KAMAL_PUBLIC_HOST` to Harvester VM IP. Keep `KAMAL_PUBLIC_HOST`
as IP unless DNS exists.

Keep `HEADROOM_BEACON=off`, `HEADROOM_TELEMETRY=off`, and `DO_NOT_TRACK=1`
in `.env.kamal.local`. Kamal forwards these values to the app, with the same
defaults when unset. The Compose override uses these defaults too. Anonymous
uploads and local telemetry collection stay disabled across upstream upgrades.
Deploy the updated config to apply these settings to an existing container.

Before deploying 0.41.0, configure a private `HEADROOM_PROXY_TOKEN` in
`.env.kamal.local` and update each remote client to send it through
`X-Headroom-Proxy-Token`. Keep provider credentials in their existing headers.
Kamal passes the proxy token as a secret only when configured. The proxy refuses
the existing network listener without authentication; this update does not
enable the unauthenticated-bind override. Review client compatibility before
deploying. Health probes remain accessible without the token.

### Browser dashboard sign-in

Open `/dashboard` and sign in through the browser prompt. Use `headroom` as
the username and the configured `HEADROOM_PROXY_TOKEN` as the password.
The browser reuses these credentials for dashboard assets and data requests.
API and WebSocket clients must keep using `X-Headroom-Proxy-Token`.
Settings retain their existing client-network and same-origin restrictions.

The current LAN deployment uses HTTP, which does not encrypt credentials in
transit. Use HTTPS when transport confidentiality is required. Never put the
token in a URL, screenshot, or command argument.

Chats created with Codex's built-in `openai` provider retain that selection.
After updating the proxy and fully quitting Codex, resume a saved chat with
`codex -c 'model_provider="headroom"' resume <thread-id>` to select the configured
Headroom provider and its token header. Run `/compact` once after resuming.
Keep the existing chat history.

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

Before redeploying, confirm the `CI` and `Docker` workflows succeeded for the `self-hosted` commit. The Docker workflow publishes the `latest` image only after its image smoke checks pass.

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

Kamal runs Qdrant and Neo4j as accessories, and `config/deploy.yml` selects
`HEADROOM_MEMORY_BACKEND=qdrant-neo4j`. Keep `.env.kamal.local` aligned
with that backend and verify both accessories are booted before relying on graph
memory.
