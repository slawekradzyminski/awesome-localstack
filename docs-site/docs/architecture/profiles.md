# Compose profiles

Each main Compose file has its own fixed project name, so switching profiles
does not produce orphan warnings. Lightweight and full still publish
overlapping host ports (`8081`, `8082`, `11434`), so stop one before starting
the other.

| Profile | File | Project | Use it for |
| --- | --- | --- | --- |
| **lightweight** | `lightweight-docker-compose.yml` | `awesome-light` | Everyday local work and classes |
| **full** | `docker-compose.yml` | `awesome-full-native` | Everything local: monitoring, ActiveMQ, email delivery, a real LLM |
| **server** | `docker-compose.server.yml` | `awesome-server` | Production on the VPS (deployed by Ansible) |
| model-mock | `docker-compose.yml` + `docker-compose.model-mock.yml` | `awesome-full-native` | Full profile with `ollama-mock` instead of Docker Model Runner (CI) |
| grpc | base file + `docker-compose.grpc.yml` | base project | Publishes the backend's native gRPC listener on `127.0.0.1:9091` |
| compatibility | `docker-compose.compatibility.yml` | its own | Runs the `ai-testers-api` course suite against two disposable backends on `127.0.0.1:14001` / `14002` |

## What differs between the main profiles

| | lightweight | full | server |
| --- | --- | --- | --- |
| Backend Spring profile | `local` (demo seed, emails to the in-memory local outbox) | `docker,demo` (demo seed, emails over JMS) | `docker,server` + `graphql,grpc` (no demo data; bootstrap admin and catalog) |
| warehouse-service / payment-service profile | `docker,demo` | `docker,demo` | `docker` |
| PostgreSQL | tmpfs, 256 MiB, data lost on recreate | named volume `postgres-data`, host port 5432 | named volume, Vault password, nightly encrypted backups |
| Emails | local outbox (`GET /api/v1/local/email/outbox`) | ActiveMQ → consumer → Mailpit (`http://localhost:8025`) | ActiveMQ → consumer → Mailpit (private) |
| SSO (Keycloak) | yes | yes | no (`APP_SSO_ENABLED=false`) |
| LLM | `ollama-mock` on `11434` | Docker Model Runner through `ollama-dmr-adapter` | `ollama-mock` (internal) |
| Monitoring | none | Prometheus, Grafana, InfluxDB | Prometheus, Grafana, Alertmanager, cAdvisor, Node Exporter, Blackbox |
| Rate limiting | off | off | on, with raised capacities for parallel course suites |
| Signing key | ephemeral per backend start | ephemeral per backend start | `JWT_SIGNING_KEY` from Ansible Vault |
| Docs wiki | `/docs/` | `/docs/` | `/docs/` on both hosts |

!!! note "Ephemeral signing key"
    Without `JWT_SIGNING_KEY` the backend generates a new RSA key at every
    start. Access tokens issued before a backend restart stop validating; the
    frontend recovers with its refresh token.

## Starting a profile

=== "lightweight"

    ```bash
    docker compose -f lightweight-docker-compose.yml up -d
    ```

=== "full"

    ```bash
    docker compose up -d
    # or, with readiness checks and cleanup of obsolete services:
    ./run-docker-compose.sh
    ```

=== "full with the LLM mock"

    ```bash
    docker compose -f docker-compose.yml -f docker-compose.model-mock.yml up -d
    ```

=== "add gRPC"

    ```bash
    docker compose -f lightweight-docker-compose.yml -f docker-compose.grpc.yml up -d
    ```

=== "server"

    ```bash
    make ansible-deploy   # never by hand on the VPS
    ```

See [Running locally](../operations/running-locally.md) for URLs and demo users.
