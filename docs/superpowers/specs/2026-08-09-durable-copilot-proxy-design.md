# Durable Copilot Proxy Design

## Goal

Make `headroom init --proxy-url <remote> -g copilot` configure GitHub Copilot CLI so subsequent plain `copilot` invocations use the user's Copilot subscription through the remote Headroom proxy, without a provider API key or wrapper command.

## Architecture

The client uses Copilot's OpenAI-compatible provider surface. Durable init writes an encoded GitHub Copilot upstream into the Headroom base URL, selects the completions wire API, and supplies a non-secret bearer seed so Copilot emits an Authorization header. The remote Headroom deployment stores the reusable GitHub Copilot OAuth credential, exchanges and refreshes short-lived API tokens, replaces the non-secret client seed, and forwards requests to `https://api.githubcopilot.com`.

Local proxy initialization keeps the existing BYOK behavior. Remote Copilot initialization selects subscription routing because a remote proxy cannot inherit workstation provider secrets or wrapper process state.

## Safety

- Upstream OAuth credentials remain in ignored Kamal deployment secrets and never enter committed client configuration.
- The client seed is explicitly non-secret and is never forwarded upstream.
- Retired context-tool cleanup must not alter instruction files tracked by the current Git repository.
- Existing user shell configuration outside Headroom's managed marker remains unchanged.

## Acceptance

- Focused init tests prove the durable remote environment contains an encoded Copilot upstream and non-secret bearer seed.
- Proxy tests prove the seed is replaced by the server-managed Copilot token.
- Cleanup tests prove tracked instruction files survive wrap cleanup.
- The rebuilt CLI installs the durable configuration.
- The rebuilt proxy deploys healthy to `10.10.10.89`.
- A fresh shell running plain `copilot -p "Reply with ok only."` returns `ok` and the request appears as Copilot through Headroom.
