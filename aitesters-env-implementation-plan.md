# aitesters.byst.re Implementation Plan

## Purpose

Create a public, disposable admin-capable testing sandbox at:

- `https://aitesters.byst.re`

The environment should let API/UI testers exercise flows that are intentionally unsafe or inconvenient on the stable shared playground at:

- `https://awesome.byst.re`

This plan is intentionally limited to deployment design and implementation steps. It does not perform the deployment.

## Current Findings

Server inspection on the current VPS showed:

- Host: Ubuntu 24.04 LTS in LXC
- RAM: 4 GiB total
- Swap: none
- Memory currently used: about 2.8 GiB
- Memory currently available: about 1.2 GiB
- Disk: 40 GiB total, about 27 GiB free
- Docker images: about 7.6 GiB, about 3.7 GiB reclaimable
- Current Compose project: `awesome-server`
- Current public listener: Docker gateway owns host port `80`
- Current public stack has 10 running containers
- `awesome.byst.re`, `aitesters.awesome.byst.re`, and `aitesters.byst.re` resolve through Cloudflare/Mikrus DNS
- TLS currently covers `byst.re` and `*.byst.re`; it does not cover nested names such as `aitesters.awesome.byst.re`

Main constraint:

- Disk is fine.
- RAM is tight.
- A second JVM backend is feasible but should be memory-capped or paired with swap.

## Decision

Deploy `aitesters.byst.re` as an additional internal app pair inside the existing server Compose project:

- `aitesters-backend`
- `aitesters-frontend`

Do not run a second public gateway. The current `gateway` service already binds host port `80`.

Instead, extend nginx host-based routing:

- `awesome.byst.re` routes to the existing `backend` and `frontend`
- `aitesters.byst.re` routes to `aitesters-backend` and `aitesters-frontend`
- `aitesters.awesome.byst.re` can remain as an nginx alias, but it is not expected to work over public HTTPS unless a dedicated nested-domain certificate is issued

Reuse the existing `ollama-mock` service from the server stack.

## Accepted Risk

The `aitesters` environment will run the backend with the `local` Spring profile.

That means local/test helpers such as the following can be publicly reachable:

- `/api/v1/local/email/outbox/**`

This is accepted for the testing playground.

Mitigation is operational rather than technical:

- Treat `aitesters.byst.re` as disposable.
- Do not store real data there.
- Reset it frequently.
- Keep production-like/stable testing on `awesome.byst.re`.

## Target Behavior

The `aitesters` sandbox should provide:

- seeded local demo admin
- seeded local client users
- seeded products and sample orders
- H2 in-memory database
- local JMS stub instead of Artemis
- local password reset outbox
- password reset token exposure, as configured by the local profile
- API and UI available under the `aitesters` hostname
- no additional Postgres, Artemis, Mailhog, Prometheus, Grafana, or consumer containers

Expected default seeded credentials from the backend `local`/demo setup:

- admin: `admin` / `LocalDemoAdmin123!`
- clients: `client` / `client`, `client2` / `client2`, `client3` / `client3`

The seeded admin credential is intentionally public for this sandbox.

## Proposed Architecture

```text
Internet
  |
  v
Cloudflare / DNS
  |
  v
VPS host port 80
  |
  v
gateway nginx container
  |
  +-- Host: awesome.byst.re
  |     +-- /api, swagger, actuator -> backend:4001
  |     +-- /                         -> frontend:80
  |
  +-- Host: aitesters.byst.re
        +-- /api, swagger, actuator -> aitesters-backend:4001
        +-- /                         -> aitesters-frontend:80
```

The `aitesters-backend` service should use:

```yaml
SPRING_PROFILES_ACTIVE: local
SERVER_FORWARD_HEADERS_STRATEGY: framework
OLLAMA_BASE_URL: http://ollama-mock:11434
PASSWORD_RESET_FRONTEND_BASE_URL: https://aitesters.byst.re/reset
SWAGGER_UI_OAUTH2_REDIRECT_URL: https://aitesters.byst.re/swagger-ui/oauth2-redirect.html
APP_CORS_ALLOWED_ORIGIN_PATTERNS: https://aitesters.byst.re,http://aitesters.byst.re,https://aitesters.awesome.byst.re,http://aitesters.awesome.byst.re
```

Recommended memory guard:

```yaml
JAVA_TOOL_OPTIONS: >-
  -XX:MaxRAMPercentage=70
  -XX:InitialRAMPercentage=20
```

Recommended Compose memory limit if supported in the target Docker Compose mode:

```yaml
mem_limit: 768m
```

If `mem_limit` is not honored in this deployment mode, rely on JVM sizing plus host-level swap.

## Implementation Steps

### 1. Confirm DNS And TLS Path

DNS already resolves for:

```bash
dig +short aitesters.byst.re A
```

Before implementation, confirm how TLS is terminated:

- If Cloudflare terminates HTTPS and talks HTTP to the VPS, nginx only needs port `80`.
- If the origin must serve HTTPS directly, add a certificate/ACME step before public rollout.

Current stack appears to depend on Cloudflare/public proxying and internal nginx on port `80`.

### 2. Add Aitest Services To Server Compose

Edit `docker-compose.server.yml`.

Add `aitesters-backend`:

```yaml
  aitesters-backend:
    image: slawekradzyminski/backend:3.6.8
    restart: unless-stopped
    hostname: aitesters-backend
    environment:
      SPRING_PROFILES_ACTIVE: local
      SERVER_FORWARD_HEADERS_STRATEGY: framework
      OLLAMA_BASE_URL: http://ollama-mock:11434
      PASSWORD_RESET_FRONTEND_BASE_URL: https://aitesters.byst.re/reset
      SWAGGER_UI_OAUTH2_REDIRECT_URL: https://aitesters.byst.re/swagger-ui/oauth2-redirect.html
      APP_CORS_ALLOWED_ORIGIN_PATTERNS: https://aitesters.byst.re,http://aitesters.byst.re,https://aitesters.awesome.byst.re,http://aitesters.awesome.byst.re
      JAVA_TOOL_OPTIONS: "-XX:MaxRAMPercentage=70 -XX:InitialRAMPercentage=20"
    depends_on:
      ollama-mock:
        condition: service_started
    expose:
      - "4001"
    mem_limit: 768m
    networks:
      - my-private-ntwk
```

Add `aitesters-frontend`:

```yaml
  aitesters-frontend:
    image: slawekradzyminski/frontend:3.6.6
    restart: unless-stopped
    expose:
      - "80"
    networks:
      - my-private-ntwk
```

Do not publish ports for either service.

Keep them internal-only behind the existing gateway.

### 3. Add Nginx Host Routing

Update `nginx/conf.d/app-gateway.conf`.

Keep the existing `awesome.byst.re` server block unchanged except for any version-neutral cleanup needed.

Add a second server block:

```nginx
server {
  listen 80;
  server_name aitesters.byst.re aitesters.awesome.byst.re;

  client_max_body_size 10m;

  location /api/v1/ws-traffic {
    proxy_pass http://aitesters-backend:4001;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-Port 443;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
  }

  location /api/v1/ {
    proxy_pass http://aitesters-backend:4001;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-Port 443;
    proxy_set_header X-Forwarded-Proto https;
  }

  location /swagger-ui/ {
    proxy_pass http://aitesters-backend:4001;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-Port 443;
    proxy_set_header X-Forwarded-Proto https;
  }

  location /v3/api-docs {
    proxy_pass http://aitesters-backend:4001;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-Port 443;
    proxy_set_header X-Forwarded-Proto https;
  }

  location /actuator/ {
    proxy_pass http://aitesters-backend:4001;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-Port 443;
    proxy_set_header X-Forwarded-Proto https;
  }

  location /images/ {
    alias /usr/share/nginx/html/images/;
    try_files $uri =404;
    access_log off;
  }

  location / {
    proxy_pass http://aitesters-frontend:80;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host $http_host;
    proxy_set_header X-Forwarded-Port 443;
    proxy_set_header X-Forwarded-Proto https;
  }
}
```

Optional cleanup:

- Extract repeated proxy headers into an include file later.
- Do not do that in the first rollout unless the diff becomes too noisy.

### 4. Update Ansible Verification

Update `ansible/inventory/group_vars/production/main.yml`.

Add public and local checks for the aitesters hostname.

Internal nginx checks can use an explicit `Host` header:

```yaml
verify_urls:
  - url: http://127.0.0.1/login
    status_code: 200
  - url: http://127.0.0.1/v3/api-docs
    status_code: 200
  - url: http://127.0.0.1/images/iphone.png
    status_code: 200
  - url: http://127.0.0.1/mailhog/api/v2/messages
    status_code: 404
  - url: http://127.0.0.1/mailhog/
    status_code: 404
```

Because the existing `verify_urls` structure does not include request headers, add a dedicated verify task for aitesters:

```yaml
- name: Verify aitesters login route through gateway host routing
  ansible.builtin.uri:
    url: http://127.0.0.1/login
    headers:
      Host: aitesters.byst.re
    status_code: 200
    return_content: false
  register: verify_aitesters_login
  until: verify_aitesters_login.status == 200
  retries: "{{ verify_retries }}"
  delay: "{{ verify_delay_seconds }}"
```

Add OpenAPI check:

```yaml
- name: Verify aitesters OpenAPI route through gateway host routing
  ansible.builtin.uri:
    url: http://127.0.0.1/v3/api-docs
    headers:
      Host: aitesters.byst.re
    status_code: 200
    return_content: true
  register: verify_aitesters_openapi
  until: verify_aitesters_openapi.status == 200
  retries: "{{ verify_retries }}"
  delay: "{{ verify_delay_seconds }}"
```

Add seeded admin sign-in check:

```yaml
- name: Sign in to aitesters with seeded local admin
  ansible.builtin.uri:
    url: http://127.0.0.1/api/v1/users/signin
    method: POST
    headers:
      Host: aitesters.byst.re
    body_format: json
    body:
      username: admin
      password: LocalDemoAdmin123!
    status_code: 200
    return_content: true
  register: verify_aitesters_admin_signin
  until: verify_aitesters_admin_signin.status == 200
  retries: "{{ verify_retries }}"
  delay: "{{ verify_delay_seconds }}"
```

Add products check using the aitesters admin token:

```yaml
- name: Verify aitesters product catalog is present
  ansible.builtin.uri:
    url: http://127.0.0.1/api/v1/products
    method: GET
    headers:
      Host: aitesters.byst.re
      Authorization: "Bearer {{ (verify_aitesters_admin_signin.content | from_json).token }}"
    status_code: 200
    return_content: true
  register: verify_aitesters_products_response
  failed_when: >
    verify_aitesters_products_response.status != 200 or
    ((verify_aitesters_products_response.content | from_json) | length) == 0
```

### 5. Add Aitest Reset Command

Add a dedicated reset playbook:

```text
ansible/playbooks/reset-aitesters-state.yml
```

Proposed content:

```yaml
- name: Reset aitesters sandbox state
  hosts: production
  become: true
  gather_facts: false

  tasks:
    - name: Recreate aitesters backend
      ansible.builtin.command:
        cmd: docker compose -f {{ app_compose_file }} up -d --force-recreate aitesters-backend
        chdir: "{{ app_dir }}"
      changed_when: true

    - name: Wait for aitesters login route
      ansible.builtin.uri:
        url: http://127.0.0.1/login
        headers:
          Host: aitesters.byst.re
        status_code: 200
        return_content: false
      register: reset_aitesters_login
      until: reset_aitesters_login.status == 200
      retries: "{{ verify_retries }}"
      delay: "{{ verify_delay_seconds }}"

    - name: Verify seeded aitesters admin after reset
      ansible.builtin.uri:
        url: http://127.0.0.1/api/v1/users/signin
        method: POST
        headers:
          Host: aitesters.byst.re
        body_format: json
        body:
          username: admin
          password: LocalDemoAdmin123!
        status_code: 200
        return_content: false
      register: reset_aitesters_admin_signin
      until: reset_aitesters_admin_signin.status == 200
      retries: "{{ verify_retries }}"
      delay: "{{ verify_delay_seconds }}"
```

Add Make target:

```make
.PHONY: ansible-reset-aitesters-state

ansible-reset-aitesters-state:
	cd ansible && ansible-playbook playbooks/reset-aitesters-state.yml --vault-password-file .vault_pass
```

Note: the current Makefile points `ANSIBLE_VAULT_FILE := .vault_pass` from the repo root, but the available vault password file is under `ansible/.vault_pass`. Fix this before relying on new Make targets:

```make
ANSIBLE_VAULT_FILE := ansible/.vault_pass
```

Then update existing Make targets if necessary so they run consistently from the repository root.

### 6. Scheduled Daily Reset

Configure a daily reset for `aitesters` as a permanent part of the environment.

Preferred implementation: systemd timer managed by Ansible.

The timer should recreate only the H2-backed `aitesters-backend` container. This clears the in-memory database and local outbox, then the backend starts again with seeded local demo data.

Recommended schedule:

- every day at `03:00` server local time
- persistent timer enabled, so a missed run executes after the VPS comes back online

Add a systemd service:

```ini
[Unit]
Description=Reset aitesters sandbox state
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=/opt/awesome-localstack
ExecStart=/usr/bin/docker compose -f docker-compose.server.yml up -d --force-recreate aitesters-backend
StandardOutput=append:/var/log/aitesters-reset.log
StandardError=append:/var/log/aitesters-reset.log
```

Add a systemd timer:

```ini
[Unit]
Description=Daily reset for aitesters sandbox

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
Unit=aitesters-reset.service

[Install]
WantedBy=timers.target
```

Enable it:

```bash
systemctl daemon-reload
systemctl enable --now aitesters-reset.timer
systemctl list-timers aitesters-reset.timer
```

Fallback cron entry if systemd timer management is not added immediately:

```cron
0 3 * * * cd /opt/awesome-localstack && docker compose -f docker-compose.server.yml up -d --force-recreate aitesters-backend >>/var/log/aitesters-reset.log 2>&1
```

Do not use hourly reset by default. If a workshop needs hourly resets, add it as a temporary operational override and remove it after the workshop.

### 7. Resource Protection

Before public rollout, add at least one of:

1. JVM memory sizing on `aitesters-backend`.
2. Compose memory limit on `aitesters-backend`.
3. Host swap.
4. VPS RAM upgrade.

Minimum recommended immediate change:

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
```

If swap is added through automation, add it to an Ansible role rather than running it manually.

Recommended post-deploy monitoring commands:

```bash
docker stats --no-stream
free -h
df -hT /
docker compose -f /opt/awesome-localstack/docker-compose.server.yml ps
```

### 8. Public Smoke Tests

After deployment:

```bash
curl -i https://aitesters.byst.re/login
curl -i https://aitesters.byst.re/v3/api-docs
curl -i https://aitesters.byst.re/images/iphone.png
```

Sign in:

```bash
curl -sS -X POST https://aitesters.byst.re/api/v1/users/signin \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"LocalDemoAdmin123!"}' | jq .
```

Product catalog:

```bash
TOKEN="$(
  curl -sS -X POST https://aitesters.byst.re/api/v1/users/signin \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"LocalDemoAdmin123!"}' | jq -r .token
)"

curl -sS https://aitesters.byst.re/api/v1/products \
  -H "Authorization: Bearer $TOKEN" | jq .
```

Accepted local helper exposure:

```bash
curl -i https://aitesters.byst.re/api/v1/local/email/outbox
```

Expected:

- `200` or valid JSON from local outbox, depending on controller behavior.
- This is intentionally accepted for the sandbox.

### 9. API Test Configuration

For `../ai-testers-api/l7`, add a local `.env.local` example for the sandbox:

```dotenv
API_BASE_URL=https://aitesters.byst.re
API_LOGIN_USERNAME=client
API_LOGIN_PASSWORD=client
API_USER_EMAIL=alice.smith@yahoo.com
API_ADMIN_USERNAME=admin
API_ADMIN_PASSWORD=LocalDemoAdmin123!
```

Admin specs should still be explicit and serial where they mutate shared state.

Recommended Playwright grouping:

- public-safe tests can run against `awesome.byst.re`
- admin/mutation tests run against `aitesters.byst.re`
- product create/update/delete tests should avoid relying on global IDs
- destructive tests should create their own entities where possible
- admin specs should run with `workers: 1` or a dedicated serial project

## Rollout Sequence

1. Commit Compose changes for `aitesters-backend` and `aitesters-frontend`.
2. Commit nginx second server block.
3. Commit Ansible verification updates.
4. Commit reset playbook and Make target.
5. Add resource guard: JVM sizing, memory limit, or swap.
6. Deploy with Ansible.
7. Verify `awesome.byst.re` still works.
8. Verify `aitesters.byst.re` works.
9. Run a small subset of L7 tests against `aitesters`.
10. Enable scheduled reset if needed.

## Rollback Plan

Fast rollback:

1. Remove or comment out the `aitesters` nginx server block.
2. Remove `aitesters-backend` and `aitesters-frontend` from Compose or scale them to zero.
3. Redeploy.

Manual server rollback:

```bash
cd /opt/awesome-localstack
docker compose -f docker-compose.server.yml stop aitesters-backend aitesters-frontend
docker compose -f docker-compose.server.yml rm -f aitesters-backend aitesters-frontend
docker compose -f docker-compose.server.yml restart gateway
```

Primary production playground rollback check:

```bash
curl -i https://awesome.byst.re/login
curl -i https://awesome.byst.re/v3/api-docs
```

## Open Questions

- Should `aitesters` use the same backend image tag as `awesome-server`, or should it track the newest published tag in the repository?
- Should the local outbox helper remain public permanently, or only during workshops?
- Should swap be managed by Ansible before rollout?
- Should `aitesters` have separate access logs or traffic labels for easier debugging?

## Recommendation

Proceed with the host-routed, local-profile `aitesters` environment, but add JVM memory limits before exposing it to users.

The lowest-risk implementation is:

- one existing public gateway
- second nginx `server_name`
- one extra backend in `local` profile
- one extra frontend
- reuse current `ollama-mock`
- no extra database, broker, mail, monitoring, or consumer services
- dedicated reset command that recreates only `aitesters-backend`
