# Local SSO Flow

This repository runs a local SSO training setup in the `lightweight`, `full`, and `ci` profiles. The identity provider is Keycloak, exposed on `localhost:8082`. The app still runs through the normal gateway on `localhost:8081`.

The `server` profile keeps SSO disabled by default. Do not point production-like deployments at this local realm; server SSO needs a real issuer, real redirect URLs, and managed credentials.

## Local URLs

| Surface | URL |
| --- | --- |
| Application login | `http://localhost:8081/login` |
| SSO callback route | `http://localhost:8081/auth/sso/callback` |
| Keycloak issuer | `http://localhost:8082/realms/awesome-testing` |
| Keycloak discovery document | `http://localhost:8082/realms/awesome-testing/.well-known/openid-configuration` |
| Keycloak Admin Console | `http://localhost:8082/admin/` |
| Backend SSO exchange endpoint | `POST http://localhost:8081/api/v1/users/sso/exchange` |

## Local Credentials

Application password login users are owned by the backend demo seed data:

| Role | Username | Password |
| --- | --- | --- |
| Admin | `admin` | `LocalDemoAdmin123!` |
| Client | `client` | `client` |
| Client | `client2` | `client2` |
| Client | `client3` | `client3` |

SSO users are owned by Keycloak:

| Role | Username | Password | Email |
| --- | --- | --- | --- |
| Client | `sso-client` | `SsoClient123!` | `sso-client@example.test` |
| Admin | `sso-admin` | `SsoAdmin123!` | `sso-admin@example.test` |

Keycloak admin access:

| Surface | Username | Password |
| --- | --- | --- |
| Keycloak Admin Console | `admin` | `admin` |

## Standard Login

Standard login is application-owned username and password authentication.

1. The user opens `http://localhost:8081/login`.
2. The user submits a backend demo username and password, for example `admin` / `LocalDemoAdmin123!`.
3. The frontend calls `POST /api/v1/users/signin`.
4. The backend validates the password against its own user table.
5. The backend returns the app access token and refresh token.
6. The frontend stores the app tokens and calls protected APIs with `Authorization: Bearer <app-access-token>`.

In this path, the backend owns the user's password, the local user record, roles, refresh tokens, carts, orders, and domain data.

## SSO Login

SSO login is identity-provider-owned authentication followed by an application token exchange.

1. The user opens `http://localhost:8081/login`.
2. The user chooses the SSO option.
3. The frontend starts the Authorization Code + PKCE flow against Keycloak client `awesome-testing-frontend`.
4. The browser is redirected to Keycloak at `http://localhost:8082/realms/awesome-testing`.
5. The user signs in with a Keycloak user, for example `sso-client` / `SsoClient123!`.
6. Keycloak redirects back to `http://localhost:8081/auth/sso/callback` with an authorization code.
7. The frontend completes the code exchange with Keycloak and receives OIDC tokens, including an ID token.
8. The frontend posts the ID token to `POST /api/v1/users/sso/exchange`.
9. The backend validates the ID token issuer, signature, expiry, and audience against the configured Keycloak realm.
10. The backend provisions a local app user when needed, or reuses the existing SSO-linked app user.
11. The backend returns the same app access token and refresh token shape used by standard login.
12. The frontend stores the app tokens and calls protected APIs with `Authorization: Bearer <app-access-token>`.

Protected application APIs do not accept raw Keycloak tokens. Keycloak proves who the user is, then the backend issues the tokens that authorize app API calls.

## Key Difference

| Area | Standard login | SSO login |
| --- | --- | --- |
| Who checks the password? | Backend application | Keycloak |
| Login form lives in | Application frontend | Keycloak-hosted page |
| Primary credential store | App database | Keycloak realm |
| Backend endpoint used by frontend | `POST /api/v1/users/signin` | `POST /api/v1/users/sso/exchange` after Keycloak login |
| Token used for app APIs | App JWT | App JWT |
| Refresh token owner | Backend application | Backend application |
| Local app user | Existing seeded/register-created user | Created or reused after validated SSO token |
| Password reset | App password reset flow | Managed by identity provider for SSO-only users |
| Main test value | App auth validation and token storage | Redirects, external identity, token exchange, user provisioning |

Both flows end in the same application session model. That is intentional: downstream app tests can exercise products, carts, orders, profiles, and admin screens without caring whether the user originally came from password login or SSO.

## Social Login (Mock Providers)

The same Keycloak instance hosts two additional realms that simulate external social identity providers:

| Mock Provider | Realm | Login URL |
| --- | --- | --- |
| Google | `google-mock` | `http://localhost:8082/realms/google-mock` |
| GitHub | `github-mock` | `http://localhost:8082/realms/github-mock` |

Social login users:

| Provider | Username | Password | Email |
| --- | --- | --- | --- |
| Google (mock) | `google-user` | `GoogleUser123!` | `google-user@gmail.com` |
| GitHub (mock) | `github-user` | `GitHubUser123!` | `github-user@github.test` |

### How It Works

The `awesome-testing` realm has two OIDC identity providers configured (`google` and `github`). These broker to the mock realms on the same Keycloak instance.

When the frontend adds `&kc_idp_hint=google` to the authorization URL, Keycloak skips its own login form and redirects the browser to the `google-mock` realm login page. The user authenticates there, and Keycloak brokers the identity back to `awesome-testing`, issuing its own token.

The backend never sees Google or GitHub tokens directly. It always validates tokens from the `awesome-testing` realm.

### Social Login Flow

1. The user opens `http://localhost:8081/login`.
2. The user clicks "Continue with Google" or "Continue with GitHub".
3. The frontend starts the Authorization Code + PKCE flow with `&kc_idp_hint=google` (or `github`).
4. Keycloak (`awesome-testing` realm) redirects the browser to the mock provider realm login page.
5. The user signs in with mock provider credentials, for example `google-user` / `GoogleUser123!`.
6. The mock realm redirects back to Keycloak's broker endpoint.
7. Keycloak provisions a federated identity and redirects back to `http://localhost:8081/auth/sso/callback`.
8. The frontend completes the code exchange and posts the ID token to `POST /api/v1/users/sso/exchange`.
9. The backend validates the token (still issued by `awesome-testing` realm) and returns app tokens.

### Upgrade Path to Real Providers

To switch from mock realms to real Google or GitHub:

1. Register an OAuth app at Google Cloud Console or GitHub Settings.
2. Replace the identity provider config in `realm-export.json` with real OAuth endpoints.
3. No changes needed in the backend or frontend code.

This is the core value of identity brokering: the application is decoupled from the identity provider details.

## Quick Checks

Start lightweight:

```bash
docker compose -f lightweight-docker-compose.yml up -d
```

Check app and Keycloak:

```bash
curl -i http://localhost:8081/login
curl -i http://localhost:8082/realms/awesome-testing/.well-known/openid-configuration
curl -i http://localhost:8081/v3/api-docs
```

Expected:

- login returns `200`
- Keycloak discovery returns `200`
- OpenAPI returns `200`

Invalid SSO token check:

```bash
curl -i -X POST http://localhost:8081/api/v1/users/sso/exchange \
  -H 'Content-Type: application/json' \
  -d '{"idToken":"not-a-real-token"}'
```

Expected:

- response is `401`
- body contains `Invalid SSO token`

