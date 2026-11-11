# Accounts, MFA and SSO

All account endpoints live in the backend under `/api/v1/users`. The token
model (RS256 access token, rotating refresh token) is explained in
[Authentication](../architecture/auth.md).

## Endpoints

| Method and path | Auth | Result |
| --- | --- | --- |
| `POST /api/v1/users/signup` `{username, email, password, firstName, lastName}` | none | `201`; always creates `ROLE_CLIENT`. Username 4–255, password 8–255, first and last name 4–255, valid email |
| `POST /api/v1/users/signin` `{username, password}` | none | `200 LoginResponseDto`; `422` wrong credentials; MFA accounts get a challenge instead of tokens |
| `POST /api/v1/users/signin/2fa` `{challengeToken, code}` | none | `200` with tokens; `401` invalid challenge or code |
| `POST /api/v1/users/refresh` `{refreshToken}` | none | `200` new access and refresh token; `401` invalid, expired, revoked or reused |
| `POST /api/v1/users/logout` | Bearer | revokes the refresh token |
| `POST /api/v1/users/password/forgot` `{identifier}` | none | always `202` (username or email; no account enumeration) |
| `POST /api/v1/users/password/reset` `{token, newPassword, confirmPassword}` | none | `200`; `400` mismatch, invalid, expired or used token |
| `POST /api/v1/users/sso/exchange` `{idToken}` | none | `200` with tokens; `401 Invalid SSO token`; `404` when SSO is disabled; `409` email already used by another provider |
| `GET /api/v1/users/me` | Bearer | current user |
| `GET /api/v1/users/me/email-events` | Bearer | the caller's latest email statuses (`QUEUED`, `SENT_TO_SMTP_SINK`, `FAILED`) |
| `GET /api/v1/users/2fa/status` | Bearer | enabled flag and remaining recovery codes |
| `POST /api/v1/users/2fa/setup` | Bearer | `{secret, otpAuthUri, qrCodeDataUri, expiresAt}`; `409` already enabled or SSO account |
| `POST /api/v1/users/2fa/confirm` `{code}` | Bearer | enables MFA, returns `recoveryCodes` once |
| `POST /api/v1/users/2fa/recovery-codes` `{password, code}` | Bearer | replaces all recovery codes |
| `POST /api/v1/users/2fa/disable` `{password, code}` | Bearer | removes MFA (TOTP or recovery code), revokes all refresh tokens |
| `GET /api/v1/users`, `GET/PUT/DELETE /api/v1/users/{username}` | Bearer | user administration (list and delete are admin only) |
| `DELETE /api/v1/users/{username}/right-to-be-forgotten` | Bearer | erases the user's data |

`LoginResponseDto`: `token`, `refreshToken`, `username`, `email`, `firstName`,
`lastName`, `roles`, `mfaRequired`, `challengeToken`, `challengeExpiresAt`.

## Password sign-in and refresh

```mermaid
sequenceDiagram
    actor U as User
    participant F as Frontend
    participant B as Backend
    U->>F: username + password
    F->>B: POST /api/v1/users/signin
    B-->>F: 200 {token, refreshToken, roles, mfaRequired:false}
    F->>F: store token + refreshToken
    Note over F,B: one hour later
    F->>B: GET /api/v1/orders (expired token)
    B-->>F: 401
    F->>B: POST /api/v1/users/refresh {refreshToken}
    B->>B: mark old token consumed, issue a new one in the same family
    B-->>F: 200 {token, refreshToken}
    F->>B: retry GET /api/v1/orders
```

If an attacker replays a refresh token that was already exchanged, the backend
revokes the whole family; the next refresh from the real user also fails and
they must sign in again.

## MFA

### Enrolment

```mermaid
sequenceDiagram
    actor U as User
    participant B as Backend
    participant A as Authenticator app
    U->>B: POST /api/v1/users/2fa/setup (Bearer)
    B-->>U: secret, otpAuthUri, qrCodeDataUri (pending 15 min)
    U->>A: scan QR / type secret
    A-->>U: 6-digit code
    U->>B: POST /api/v1/users/2fa/confirm {code}
    B-->>U: recoveryCodes (shown once)
```

### Sign-in with a second factor

```mermaid
sequenceDiagram
    actor U as User
    participant B as Backend
    U->>B: POST /api/v1/users/signin {username, password}
    B-->>U: 200 {mfaRequired:true, challengeToken, challengeExpiresAt} (no tokens)
    U->>B: POST /api/v1/users/signin/2fa {challengeToken, code}
    alt code valid (current step ± 1, not replayed) or unused recovery code
        B-->>U: 200 {token, refreshToken}
    else
        B-->>U: 401
    end
```

Rules worth testing:

- The challenge is single-use, expires after 5 minutes and is invalidated by a
  newer password sign-in.
- A TOTP code is accepted for the current 30-second step and one step either
  side, and the same step cannot be used twice.
- A recovery code works once.
- Password reset does **not** disable or bypass MFA.
- Disabling MFA and regenerating recovery codes need the current password and
  a second factor.

## Password reset

```mermaid
sequenceDiagram
    actor U as User
    participant B as Backend
    participant M as Email (outbox / Mailpit)
    U->>B: POST /api/v1/users/password/forgot {identifier}
    B-->>U: 202 "If the account exists, ..."
    B->>B: delete older tokens, store a hash of a new 32-byte token (valid 30 min)
    B->>M: PASSWORD_RESET_REQUESTED with link .../reset?token=...
    U->>B: POST /api/v1/users/password/reset {token, newPassword, confirmPassword}
    B->>B: set password, revoke all refresh tokens, delete reset tokens
    B->>M: PASSWORD_RESET_CONFIRMED
    B-->>U: 200
```

- The link base is `PASSWORD_RESET_FRONTEND_BASE_URL` (`http://localhost:8081/reset`
  locally, `https://awesome.byst.re/reset` in production).
- SSO-only accounts get no reset email (the response is still `202`).
- In the lightweight profile (`local`) the response also contains the raw
  `token` (`expose-token-in-response: true`) and the email is visible in the
  local outbox `GET /api/v1/local/email/outbox`; other profiles never expose it.

## SSO (local profiles)

```mermaid
sequenceDiagram
    actor U as User
    participant F as Frontend
    participant K as Keycloak :8082
    participant B as Backend
    U->>F: Sign in with SSO
    F->>K: /authorize (code + PKCE, client awesome-testing-frontend)
    U->>K: sso-e2e-client / SsoClient123!
    K-->>F: redirect /auth/sso/callback?code=...
    F->>K: /token (code + verifier)
    K-->>F: id_token
    F->>B: POST /api/v1/users/sso/exchange {idToken}
    B->>K: JWKS (cached), validate issuer, audience, signature, expiry
    B->>B: find or provision local user (preferred_username, email, names)
    B-->>F: 200 {token, refreshToken}
```

Keycloak users: `sso-e2e-client` / `SsoClient123!`, `sso-admin` /
`SsoAdmin123!`; mock social providers `google-user` / `GoogleUser123!` and
`github-user` / `GitHubUser123!` through the `google-mock` and `github-mock`
realms. Keycloak admin console: `http://localhost:8082/admin/` (`admin` /
`admin`). See [SSO flow](../reference/SSO_FLOW.md) and
[Social login](../reference/SOCIAL_LOGIN.md).
