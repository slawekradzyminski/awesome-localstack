# Public Hardening Implementation Plan

## Goal

Harden `https://awesome.byst.re` so it can be recommended publicly as a live demo, while preserving the local/demo training workflow in the underlying repositories.

This is not a frontend-only effort. The public deployment currently needs coordinated backend, deployment, and documentation changes before it is safe to promote.

## Current Public-State Summary

Verified on March 29, 2026:

- `https://awesome.byst.re/login` responds
- `https://awesome.byst.re/v3/api-docs` responds
- `https://awesome.byst.re/mailhog/api/v2/messages` is publicly reachable
- `POST /api/v1/users/signin` accepted `admin/admin`
- the resulting admin token could enumerate users via `GET /api/v1/users`

Conclusion:

- the deployment is operational
- it is not yet ready for public recommendation

## Repository Scope

### `test-secure-backend`

Purpose:

- remove test/demo behavior from the public deployment path
- keep local/demo profiles productive
- provide a public-safe email verification flow owned by the application

Reported branch status:

- branch: `hardening`
- latest commit: `cd1634d`
- commit message: `Add user email event visibility for public-safe demo`

Backend hardening already reported as completed on that branch:

- demo seed loading disabled by default for server/public deploys
- local/demo profiles still support seed data
- signup is server-forced to `ROLE_CLIENT`
- signup request no longer exposes roles in the public contract
- admin bootstrap is env-driven instead of relying on seeded demo admins
- user edit flow has regression coverage against privilege escalation
- `./mvnw -Pfast-verify verify` passed

New backend capability on top:

- authenticated endpoint: `GET /api/v1/users/me/email-events`
- this returns only the current user’s recent email events
- it is the public-safe replacement for Mailhog visibility

Email-event status model:

- `QUEUED`
- `SENT_TO_SMTP_SINK`
- `FAILED`

Important deployment implication:

- do not expose `/mailhog/api/*` publicly just to show whether email was sent
- use the backend-owned email-event endpoint instead

Important unresolved item:

- backend image publish status for `slawekradzyminski/backend:3.6.0` was not fully confirmed
- safe current statement:
  - code is committed at `cd1634d`
  - tests passed
  - multi-arch build for `3.6.0` was started
  - publish completion still needs confirmation before deploy uses that tag

### `vite-react-frontend`

Purpose:

- frontend polish and branding alignment for the public demo

Reported branch status:

- repo: `/Users/admin/IdeaProjects/vite-react-frontend`
- branch is 4 commits ahead of base `312cdaa`

Net scope against main:

- 77 files changed
- around 2755 insertions
- around 1705 deletions

Reported frontend scope:

- broad visual refresh across shell, navigation, home, auth, LLM, admin, checkout, email, QR, profile, cart, products, traffic, and users pages
- shared UI cleanup with `badge.tsx` and `surface.tsx`
- branding updates with AT assets and favicon changes
- toast restyle and behavior fix
- Playwright and accessibility/responsive coverage improvements

Notes:

- frontend work is separate from public-surface hardening
- frontend is intentionally excluded from the immediate implementation pass here

### `awesome-localstack`

Purpose:

- remove public test-only surfaces
- update deploy/verify/docs to match the safer public boundary
- redeploy the stack once backend artifacts are ready

Required work:

1. Remove public Mailhog exposure
- remove the `/mailhog/api/` nginx proxy
- keep Mailhog reachable only through SSH tunnels
- update docs accordingly

2. Update verification strategy
- stop treating Mailhog public reachability as part of the public-ready deployment
- use app-owned checks instead
- once backend `3.6.0` is available, add a public-safe verification path based on:
  - password-reset request returns `202`
  - authenticated `GET /api/v1/users/me/email-events` returns a recent event
  - `/mailhog/api/*` is not publicly reachable

3. Prepare deployment to consume the hardened backend
- confirm the `3.6.0` backend image is published
- update `docker-compose.server.yml`
- deploy via Ansible

4. Clean live state
- existing seeded users already in the live database will not disappear automatically
- after deploying the hardened backend, reset or clean the live DB state so:
  - `admin/admin` no longer works
  - old seeded accounts are removed unless intentionally retained

5. Update docs
- remove public Mailhog references from public/demo docs
- document the public-safe email-event workflow instead of Mailhog API access

## Recommended Implementation Order

1. Confirm backend and frontend image publish status for `3.6.0`
2. In `awesome-localstack`, remove public Mailhog exposure and update docs
3. Update deploy/verify logic to the new public-safe assumptions
4. Point server compose to the hardened backend tag
5. Deploy to `awesome.byst.re`
6. Clean/reset live seeded data
7. Re-run public readiness checks

## Public Go-Live Criteria

The deployment is ready for public recommendation only when all of these are true:

- `admin/admin` and other seeded demo credentials no longer work publicly
- public signup cannot create admin users
- `/mailhog/api/*` is not publicly reachable
- the live app still serves the main UI successfully
- public-safe email verification works through backend endpoints, not Mailhog
- docs reflect the actual public surface

## Suggested Verification After Hardening

1. `GET https://awesome.byst.re/login` returns `200`
2. `GET https://awesome.byst.re/v3/api-docs` returns `200`
3. `POST /api/v1/users/signin` with old seeded credentials fails
4. `GET https://awesome.byst.re/mailhog/api/v2/messages` does not return public inbox data
5. trigger a password reset or other user-owned email flow
6. authenticate as that user
7. `GET /api/v1/users/me/email-events` returns a recent event with expected status

## Restart Prompt For Next Session

Use this after `/compact`:

```text
We are hardening https://awesome.byst.re so it can be recommended publicly as a live demo.

Current context:
- repo 1: /Users/admin/IdeaProjects/test-secure-backend
- repo 2: /Users/admin/IdeaProjects/awesome-localstack
- frontend repo exists too, but exclude frontend work for now

Backend status:
- branch: hardening
- latest backend commit: cd1634d
- backend hardening is reported complete on that branch:
  - no default public seed loading for server/public deploys
  - signup is forced to ROLE_CLIENT
  - signup contract no longer exposes roles
  - admin bootstrap is env-driven
  - privilege-escalation regression coverage exists
  - ./mvnw -Pfast-verify verify passed
- new backend endpoint exists for public-safe email verification:
  - GET /api/v1/users/me/email-events
- backend image build for 3.6.0 was started, but publish completion still needs confirmation before deployment consumes that tag

awesome-localstack tasks to implement:
1. remove public /mailhog/api exposure from nginx
2. keep Mailhog accessible only via SSH tunnels
3. update docs to stop treating Mailhog as part of the public surface
4. update deploy/verify strategy to use public-safe app checks instead of Mailhog exposure
5. once backend:3.6.0 is confirmed published, update docker-compose.server.yml and deploy
6. clean/reset live seeded DB state so admin/admin and old seeded users are gone

Goal:
- make awesome.byst.re operationally and reputationally safe for public sharing
- preserve local/demo workflow in local environments

Please start by:
1. confirming whether slawekradzyminski/backend:3.6.0 is published
2. reviewing awesome-localstack for the Mailhog public exposure and current verify/docs assumptions
3. implementing the awesome-localstack hardening changes first
```
