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

Fresh native build, final affected-suite results, hosted CI, image publication and
deployment acceptance are pending. This document does not authorize deployment.
