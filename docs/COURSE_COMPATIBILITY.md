# Local course compatibility verification

The compatibility runner executes a frozen revision of `ai-testers-api` against
two disposable H2-backed instances of the existing backend. It preserves the
lesson TypeScript files and assertions, recreates fixtures for each lesson,
and stops its containers when finished. It does not use the running lightweight
stack or either public deployment.

## Run

Requirements: Docker Compose, Python 3.12 or newer, Git, and the Node/npm version
required by the course. Keep ports 14001 and 14002 available.

From `awesome-localstack`:

```bash
python3 scripts/verify-course-compatibility.py \
  --course-repo ../ai-testers-api \
  --ref HEAD \
  --lessons l20 \
  --output outputs/course-baseline-l20
```

The output directory must not already exist. For all lesson checkpoints:

```bash
python3 scripts/verify-course-compatibility.py \
  --ref <recorded-course-commit> \
  --lessons all \
  --output outputs/course-baseline-all
```

The runner uses `git archive`, so uncommitted course changes are recorded as
dirty state but are not included. It does not read or modify the participant's
`.env` or `.env.local`. The local user fixture reproduces the names and email
asserted by early lessons; admin access uses the existing local demo seed.
No email delivery service is configured in this local profile.

Only `http://127.0.0.1:14001` and `http://127.0.0.1:14002` are accepted as
effective Playwright project base URLs after importing the lesson config. The
guard fails rather than silently correcting a public/default URL. This protects
the inspected course's configured targets; it is not a network sandbox for
arbitrary untrusted test code.

The wrapper sets one worker and zero retries for a clear baseline and disables
traces. It only adds reporting/execution settings; it checks a digest of lesson
TypeScript before and after the run. Failed, flaky, skipped, or empty test runs
do not pass the gate. A lesson with no configuration is recorded separately as
scaffolding, not counted as a passing suite.

## Stack and profiles

`docker-compose.compatibility.yml` is a standalone verification profile, not an
override for lightweight/full/server. It publishes only loopback ports:

| Service | URL | Purpose |
| --- | --- | --- |
| `backend` | `http://127.0.0.1:14001` | Ordinary API course tests |
| `admin-backend` | `http://127.0.0.1:14002` | Admin course tests with isolated data |
| `ollama-mock` | Internal only | Deterministic model dependency |

The default stack verifies REST directly. The optional `graphql-preview` Compose
profile also starts the pinned frontend and nginx, reusing the actual lightweight
gateway configuration on `http://127.0.0.1:14081`. The runner checks equal GraphQL
responses directly and through nginx, plus unauthenticated rejection on both
routes. Browser, SSO, and PostgreSQL concurrency verification remain separate gates.

The ordinary backend uses `local,server`: local H2 fixtures with the existing
server profile's course-compatible UUID refresh tokens, public traffic routes,
and traffic sanitization. The admin backend uses `local`, retains secure
43-character refresh tokens and protected traffic routes, and enables traffic
sanitization. This matches the distinct token formats asserted by the ordinary
and admin course projects. Neither returns password reset tokens in responses.

The runner sets seeded product prices to `10.00` through the existing admin
REST API. Course cart assertions compare JavaScript floating-point products
exactly with server decimal totals; for example, `999.99 * 3` is
`2999.9700000000003`, whereas the correct decimal total is `2999.97`. Exact-valued
local fixtures let the unchanged course assertions run without changing backend
money arithmetic. This baseline is therefore not proof that those assertions
work for every catalog price. Backend decimal-money tests remain necessary.

The pinned default backend image is the baseline. To test a locally built
candidate without publishing it:

```bash
COMPAT_BACKEND_IMAGE=your-local-candidate-image \
  python3 scripts/verify-course-compatibility.py \
  --ref <same-recorded-course-commit> \
  --lessons l20 \
  --output outputs/course-candidate-l20
```

To check GraphQL in both direct and proxied requests,
reserve port 14081 as well and add `--graphql-preview`:

```bash
COMPAT_BACKEND_IMAGE=your-local-candidate-image \
  python3 scripts/verify-course-compatibility.py \
  --ref <same-recorded-course-commit> \
  --lessons all \
  --graphql-preview \
  --output outputs/course-candidate-graphql
```

The candidate includes the GraphQL Spring profile automatically. This flag only
starts the gateway services and runs the extra GraphQL checks; it does not enable
or disable the API. The pinned baseline image predates GraphQL. The existing
frontend still uses REST.

Use the same test commit for baseline and candidate. Record the candidate image
ID and source revision. Rate limits remain enabled with training capacities
matching the stable server's configured values; this runner does not replace
dedicated rate-limit boundary tests.

The runner refuses overlapping runs and an already-running compatibility stack.
If a process was forcibly killed, inspect and remove only this stack before
retrying:

```bash
docker compose -f docker-compose.compatibility.yml ps
docker compose -f docker-compose.compatibility.yml down --remove-orphans
```

## Evidence and handling failures

`summary.json` records course/source revisions, dirty state, suite source
digests, targets, test counts, failures, and container image references. Each
lesson directory holds OpenAPI snapshots, setup/run logs, and a Playwright JSON
report. Reports are private local artifacts under ignored `outputs/`; raw test
failure details can contain local tokens and fixture data. Publish only a
sanitized summary.

If the runner aborts, inspect its logs and summary; incomplete runs are not
compatibility evidence. Compare both exit status and test counts/skips when
evaluating a candidate. Do not change course assertions to hide a regression.

See [the phased implementation plan](GRAPHQL_GRPC_IMPLEMENTATION_PLAN.md) for
protocol-specific, mutation, deployment, and rollback gates.

## Course checks with the native gRPC listener active

Use the optional override while running the unchanged latest lesson:

```bash
COMPAT_BACKEND_IMAGE=awesome-backend:grpc-local \
  python3 scripts/verify-course-compatibility.py --lessons l20 \
  --graphql-preview --grpc-preview --output outputs/grpc-candidate-l20
```

`--grpc-preview` requires an explicit candidate image. It adds the gRPC override
only to the disposable ordinary backend, publishes its listener on loopback
14991, and checks that the port is reachable before the REST lesson runs. The
admin comparison backend still uses the same candidate image with its original
profiles. The frozen course sources, URL validation, and HTTP test assertions
are unchanged. Full native protocol/status checks are recorded separately in
[the gRPC verification report](GRPC_VERIFICATION.md).
