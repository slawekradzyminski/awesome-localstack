# Semantic Mutant Pilot Results

Run date: 2026-08-02. Generator: Codex. Corpus: eight frozen,
compile-valid semantic patches across four repositories.

| Mutant | Initial | After strengthening | Missing proof exposed |
| --- | --- | --- | --- |
| backend partial SSO account blocked | survived | killed | incomplete provider metadata must not disable local password reset |
| backend authenticated route double-counted | survived | killed | user rate limiting and anonymous IP fallback are mutually exclusive |
| frontend clears PKCE before exchange | killed | killed | callback state survives transient exchange failure |
| frontend discards previous SSE chunk | killed | killed | protocol events span arbitrary transport chunks |
| frontend enables training SSO on any loopback port | survived | killed | implicit SSO belongs only to the `:8081` training gateway |
| mock tool call uses token delay | killed | killed | tool and token latency policies are distinct |
| mock conversation uses first message | killed | killed | the latest meaningful message advances a tool scenario |
| consumer drops legacy FQCN type ID | survived | killed | both producer type identifiers remain deserializable |

Initial detection was 4/8 (50%). After four contract-level test additions, the
same frozen corpus reached 8/8. All eight patches compiled; no compiler rejection
was counted as a kill. Focused compile-plus-test execution took approximately
32 seconds for the initial corpus and 31 seconds after strengthening, excluding
the runner's baseline validation copies.

## What changed in the tests

- `PasswordResetServiceTest` now covers an account with provider metadata but
  no provider subject. The database permits this partial state, so it is a
  meaningful migration/resilience contract rather than an artificial input.
- `AuthRateLimitGuardTest` now proves that authenticated email and QR traffic
  never resolves or consumes an IP fallback bucket and adds a no-extra-calls
  oracle.
- `runtimeConfig.test.ts` now rejects implicit SSO on unrelated localhost and
  `127.0.0.1` ports.
- `JmsConfigTest` now deserializes an actual text message carrying the legacy
  fully-qualified type identifier instead of checking only serialization.

## Interpretation

The backend had already reached 100% PIT test strength for covered mutants, yet
both Codex-authored backend mutants survived. There is no contradiction: PIT
measured resistance to its operator set, while these patches changed policy
across state combinations and control-flow intent. Operator-complete does not
mean specification-complete.

The four initial kills also matter. Earlier mutation feedback had already added
the precise retry, byte-boundary, virtual-time, and multi-turn tests that caught
the semantic variants. Traditional mutation therefore strengthened the suite
for defects outside the exact framework operator that originally motivated the
tests.

This is a tiny, test-aware engineering pilot, not a model benchmark. Codex had
seen the tests before authoring the corpus, and the selected contracts were
human-reviewed only after execution. A controlled article experiment should
freeze a blind, independently reviewed corpus before any test agent sees it and
retain a second hidden holdout to measure overfitting.

Raw execution records:

- [`results/latest.json`](./results/latest.json): initial 4 killed / 4 survived;
- [`results/after-strengthening.json`](./results/after-strengthening.json):
  8 killed / 0 survived.
