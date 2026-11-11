# Codex Usage > Limits triage

## Finding

The loss is strongly attributable to T3 commit [`c9dfc404`](https://github.com/pingdotgg/t3code/commit/c9dfc404ccde9a4c8be901b287026dd19e4ed19a) (#18622), present in the reported Homebrew build source [`7e565c510d6dfaef2e1fd97bf9d89a97ce9cece7`](https://github.com/pingdotgg/t3code/commit/7e565c510d6dfaef2e1fd97bf9d89a97ce9cece7). At the prior revision [`3a8c250`](https://github.com/pingdotgg/t3code/commit/3a8c250cb0c8056f2f563091fd412fe5db809fa1) and the direct parent of c9dfc404, the Codex probe requested `account/rateLimits/read` unless native usage was explicitly skipped. c9dfc404 added `codexRoutesSpendNativeQuota` and only sends that RPC after confirming an OpenAI-native route. The 7e565c source and current `main` contain this gate.

Headroom's upstream Codex config selects a custom provider with an HTTP loopback base URL and `requires_openai_auth=true`. T3's new predicate accepts only HTTPS `api.openai.com` or `chatgpt.com` endpoints (or a confirmed default native route), so the Headroom route fails the predicate regardless of Headroom's separate remote-URL support. T3 consequently skips the quota RPC, sets native usage false, and reports `unsupported` with no windows despite ready/authenticated provider status. This matches the observed empty Limits view.

## Endpoint and attribution

This is a T3 attribution-policy gate, not evidence that Codex's quota endpoint is unavailable. The existing report says a prior initialized, read-only Codex app-server probe against the effective route returned a primary window. I did not repeat that probe. The current local Codex provider cache independently shows `status=ready`, `usageLimits.windows=[]`, and `unavailable.reason=unsupported`.

The gate was intentionally added to avoid attributing a stored ChatGPT login's quota to arbitrary custom providers. Whether it should suppress the quota for this subscription-authenticated forwarding proxy is the product decision raised by the report. The PR's own evidence notes that stored-ChatGPT quota suppression and native subscription controls were not live-verified because first-party ChatGPT OAuth was unavailable.

## Runtime and evidence limits

- The active Linux Desktop executable is under a Homebrew Caskroom build directory labeled with source prefix `7e565c510d6d`; the full source SHA above is supplied by the reporter. The local environment endpoint separately reports server version `0.1.9`, which is not a source SHA.
- The `codex.json` cache has a fresh ready/unsupported snapshot. No credentials or account identifiers were read or included.
- I inspected GitHub source and issue history, not an unmodified upstream runtime. No source clone, build, tests, app-server probe, UI acceptance, restart, or configuration change was performed.

## Existing report and duplicates

The existing comment [#23054 comment 6805363581](https://github.com/pingdotgg/t3code/issues/23054#issuecomment-6805363581) is accurate on the source-level causal chain and appropriately distinguishes the app-server probe from a full application test. Its updated Headroom upstream link and exact T3 source SHA are appropriate; no correction is required. Keep its explicit caveat that no patched-UI acceptance or unmodified upstream runtime test is claimed.

Issue [#23054](https://github.com/pingdotgg/t3code/issues/23054) originally concerns duplicate native/hub quota tiles, so this is a related regression documented in that thread rather than an exact duplicate. [#27873](https://github.com/pingdotgg/t3code/issues/27873) has a similar missing-limits symptom but concerns T3-managed ChatGPT token sharing and a different skip path. [#11515](https://github.com/pingdotgg/t3code/issues/11515) is related multi-account proxy attribution behavior. No exact existing report for this Headroom forwarding-route regression surfaced in the bounded search.

The current `main` Codex provider source still contains the gate; the targeted commit search found no later quota-gate fix. No issue, comment, PR, or other publication was created or changed.
