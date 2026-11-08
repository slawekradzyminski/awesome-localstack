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

## Inventory feature extensions (2026-08-16)

Four requirement-driven inventory mutants were added after the original pilot.
They remain separate from the original eight-mutant score and were executed as
bounded feature checks:

| Mutant | Result | Requirement exercised |
| --- | --- | --- |
| backend removes the product lock | killed | concurrent checkout cannot sell the final unit twice |
| backend commits a partial checkout | killed | multi-line checkout is atomic on a stock conflict |
| backend restores cancelled stock twice | killed | cancellation compensation is exactly once |
| frontend rotates the request ID after conflict | killed | an unchanged adjustment retry preserves its idempotency key |

All four baseline copies passed, every mutant compiled, and the focused tests
killed each mutant. Raw records are in
[`results/inventory-backend.json`](./results/inventory-backend.json) and
[`results/inventory-frontend.json`](./results/inventory-frontend.json).

## JMS email broker contract (2026-11-07)

Generator: Claude (test-aware, white-box). Scope: the email event that
`test-secure-backend` publishes and `jms-email-consumer` consumes. Before this
change both sides mocked JMS (`EmailServiceTest`, `EmailConsumerTest`), so a
destination, type-header or payload rename on either side passed both suites.

New tests share one fixture, `src/test/resources/contracts/email-jms-contract.json`,
kept byte-identical in both repositories:

- backend `EmailJmsProducerContractTest`: the real `EmailService` publishes the
  fixture's email to the embedded Artemis broker; the raw `TextMessage` on the
  fixture's queue must carry the fixture's `_awesome_` type id and a JSON body
  equal to the fixture payload. It also checks `activemq.destination` in
  `application-docker.yml`, the profile awesome-localstack runs.
- consumer `EmailJmsBrokerContractTest`: a Testcontainers `apache/artemis:2.55.0`
  broker (the compose image) receives the fixture through the backend's Artemis
  core client; the application's own OpenWire listener, converter and default
  destination must bind the full `EmailDto` and send the rendered email.

| Mutant | Initial | After strengthening | Contract |
| --- | --- | --- | --- |
| backend queue renamed to `emails` in every profile | killed | killed | publish to the queue the consumer listens on |
| backend serializes `message` as `body` | killed | killed | payload field names match the consumer's DTO |
| backend type header uses the simple class name | killed | killed | `_awesome_` carries an id the consumer resolves |
| consumer default destination renamed to `emails` | killed | killed | listen on the queue the backend publishes to |
| consumer binds `message` from `body` | survived | killed | every producer field is bound, not only rendered ones |
| consumer reads the type id from `_type` | killed | killed | read the header the backend writes |

Invalid: 0 (all six baselines passed and every mutant compiled). Equivalent: 0.
The survivor was meaningful: the fixture uses `PASSWORD_RESET_REQUESTED`,
whose rendering ignores `subject` and `message`, so asserting only the sent
email missed a rename that would blank every `GENERIC` email from `/email`.
The consumer test now also compares the bound `EmailDto` with the fixture.

Residual risk: the two fixture copies can drift if one repository edits its
copy alone; keep them identical (`cmp` the two files) when changing the
contract. The run used temporary manifest paths pointing at feature
worktrees; `manifest.json` records the default sibling checkouts.

Raw records:
[`results/email-jms-contract-initial.json`](./results/email-jms-contract-initial.json)
(5 killed / 1 survived) and
[`results/email-jms-contract-after-strengthening.json`](./results/email-jms-contract-after-strengthening.json)
(6 killed / 0 survived).

## Commerce and warehouse fulfilment (2026-11-08)

Three white-box semantic mutants target the coupon, returns, fulfilment and
idempotent-checkout rules added to `test-secure-backend`. They were frozen
after the feature tests existed, so this run measures whether those tests
encode the requirements rather than strengthening them.

| Mutant | Result | Requirement it violates |
| --- | --- | --- |
| refund ignores the coupon discount | killed | refunds return discounts proportionally (108.00 of a 126.00/140.00 order, not 120.00) |
| customer cancels a picked shipment | killed | only the warehouse may cancel once picking started; customers get 409 |
| idempotency key looked up globally | killed | keys are scoped per user; another user's key never replays or conflicts |

Invalid: 0 (all baselines passed and every mutant compiled). Equivalent: 0.
Survived: 0.

The same change ran framework mutation separately (not merged into this
score): PIT on the new and changed services went from 39 survivors to 3
equivalent-or-removed survivors after targeted unit tests, and StrykerJS
killed every mutant in the changed role and API-client code.

The run used a temporary manifest pointing at the backend feature worktree;
`manifest.json` records the default sibling checkout, so these patches apply
once the feature branch is merged.

Raw record:
[`results/commerce-fulfilment-2026-11-08.json`](./results/commerce-fulfilment-2026-11-08.json)
(3 killed).

**Moved to warehouse-service.** Returns, refunds and shipment cancellation
leave the backend for the new `warehouse-service` (see
`docs/WAREHOUSE_SERVICE_CONTRACT.md` on the warehouse-service branch). The
"refund ignores the coupon discount" and "customer cancels a picked shipment"
mutants therefore no longer apply to `test-secure-backend`: their patches and
manifest entries are removed, and they will be re-authored against
warehouse-service. The raw record above keeps the original 3-killed run; only
the idempotency-key mutant remains active for the backend.

## Commerce wave 2 stack wiring — 8 November 2026

Two requirement-driven candidates for the aitesters warehouse pairing were
frozen before strengthening the checks:

| Mutant | Violated requirement | Before | After |
| --- | --- | --- | --- |
| `stack-sandbox-warehouse-reuses-stable-env` | Stable-site JWTs and the stable service token must not authenticate at the sandbox warehouse-service | survived | killed |
| `stack-sandbox-gateway-routes-to-stable-warehouse` | Warehouse requests on the aitesters host must reach `aitesters-warehouse-service` | survived | killed |

`scripts/verify-release-images.py` now requires the sandbox warehouse to use
only `.env.aitesters-warehouse`, to call `aitesters-backend`, and each gateway
host to set its own `$warehouse_upstream`; both checks pass on the original.
`stack-certificate-mutable-source` was regenerated with the same intent because
the native consumer no longer has a blocklist mount (the old patch was
`invalid-patch`). The re-run killed all five stack cases it covered.
Killed: 5. Survived: 0. Invalid: 0. Equivalent: 0. No PIT/Stryker-scoped code
changed in this repository.

Raw record:
[`results/wave2-warehouse-20261108.json`](./results/wave2-warehouse-20261108.json).

**Upgrade stop-set fix (same day).** The first wave-2 deploy failed before stopping anything:
the backend-upgrade role named `warehouse-service`, which the previously deployed
Compose file does not define. The role now stops only the intersection of the
backend/warehouse services with the deployed file's `config --services`.
`stack-backend-upgrade-backs-up-before-quiescing` was regenerated against the new
task layout (it had become `invalid-patch`) and is killed by the updated
`scripts/verify-backend-upgrade.py`, together with two wave-2 cases re-run as a
regression check. Killed: 3. Survived: 0. Invalid: 0. Equivalent: 0. Raw record:
[`results/backend-upgrade-first-warehouse-20261108.json`](./results/backend-upgrade-first-warehouse-20261108.json).
