# Self-hosted upstream reconciliation, November 21

Baseline fork: `110423d37ccc5e3ecae732954725eedaa139c8bd`.
Upstream: `e27f0d96cc3032d5f2c510ac97545553b867a697` (52 new commits).

## Preservation

Kamal configuration, secret forwarding, persistent storage, external Qdrant/Neo4j,
600-second proxy timeout, telemetry-off defaults, Dockerfile, single amd64
`runtime-self-hosted` image, release workflows and Homebrew dispatch are unchanged
from the fork baseline. Operator quota collection and T3 hub reporting remain.

The OpenAI handler conflict combines the explicit OpenRouter chat backend with
upstream's destination-aware resolver, preserving Copilot's own upstream when
cross-provider route advice is present. The OpenCode conflict retains upstream's
extra-model support alongside the fork's configuration handling.

Upstream's removal of obsolete RTK agent instructions is retained in `AGENTS.md`
and `.github/copilot-instructions.md`; this removes no runtime capability.

Two test fixtures required repair: the Copilot streaming request now uses a real
HTTPX request with trace extensions, and the cache-only savings history test uses
the documented fallback pricing path rather than an installed model-price table.
Both failures were observed before those test-only changes; their affected suites
then passed all 48 tests. Upstream's two new CRLF text assets are normalized to LF.

## Verification boundary

Initial focused check with the existing native extension: 428 passed, four skipped.
Fork CLI/subscription check: 362 passed, one skipped. Ruff check and format check
passed on all 108 changed Python files. These are local checks, not hosted CI or
deployed acceptance.

The broader changed-test check initially passed 1,739 tests and failed nine.
One was the pricing fixture above. The other eight require qualification with a
fresh native extension: the existing extension lacks `minify_json` and predates
the new compaction encoding. Do not treat that stale extension as native proof.
The preservation batch initially passed 389 tests and failed the Copilot fixture
above, which subsequently passed after its fixture repair.

The fresh native wheel built successfully in the repository's Dagger environment
(Linux, Python 3.11, Rust 1.95.0). Its SHA256 is
`6ca51bd3ce05aa93728cdfad6d09f00dac119506ea60ed2241c1c8d9c2c5f104`.
Using that extension, all eight stale-native failures disappeared: the complete
codec/router selection passed 219 tests with one skip. A clean install with all
advertised runtime extras imported native SmartCrusher and ran the CLI successfully.

The combined 2,373-case run then exposed ten order-dependent failures: a hub test
left the process-wide stateless flag enabled, disabling persistence in the new
restart/hash tests. Running a single hub test before those ten cases reproduced
all failures. The shared test fixture now restores the flag after each test;
all 74 hub/operator/restart cases passed together. No runtime flag semantics change.
The final combined suite passed: **2,364 passed, nine skipped**, with the fresh
native extension and test-isolation repair. This selection combines all changed
upstream test modules with the focused fork preservation, deployment, reporting,
quota, CLI, authentication, realtime and routing suites.

## Real behavior commands

From the worktree, using the existing Python 3.12 project interpreter as `python`:

```bash
dagger --progress plain call build-wheel export --path /tmp/headroom-wheel
dagger --progress plain call smoke-wheel --extras proxy,code,memory-stack,bedrock
HEADROOM_OFFLINE=1 PYTHONPATH="$PWD" python -m pytest -q tests/test_transforms/test_compaction_codec.py tests/test_transforms/test_content_router.py tests/test_transforms_content_router.py
HEADROOM_OFFLINE=1 PYTHONPATH="$PWD" python -m pytest -q tests/test_hub_reporting_routes.py tests/test_codex_operator_quota.py tests/test_prefix_tracker_restart.py
```

The Python tests used the freshly built wheel's extension, rather than the
pre-existing source-checkout extension. The example export directory is disposable;
the task's actual export directory is removed at handoff.

Hosted CI, image publication and deployment acceptance remain separate pending
gates. No live provider inference or deployment was performed. Ruby/dotenv tests
were skipped locally; both compatibility versions passed in the initial hosted run.
This document does not authorize deployment.
