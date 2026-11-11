# Operations

| Task | Page |
| --- | --- |
| Start a profile, find URLs and demo users | [Running locally](running-locally.md) |
| Explore the APIs (Swagger UI, OpenAPI, GraphiQL, gRPC) | [API explorers](api-explorers.md) |
| Deploy to the VPS with Ansible, Vault keys, verification | [Production deployment](production.md) |
| Release flow per repository, image pinning by digest | [Releases and image pinning](releases.md) |
| Prometheus, Grafana, Alertmanager, probes | [Monitoring and alerts](monitoring.md) |
| Encrypted PostgreSQL backups and restore checks | [Backups](backups.md) |
| Common failures and their fixes | [Troubleshooting](troubleshooting.md) |
| How this wiki is built and served | [This documentation site](docs-site.md) |

```mermaid
flowchart LR
    subgraph Laptop
        R[awesome-localstack checkout] -->|make ansible-deploy| A[Ansible]
    end
    subgraph VPS["VPS (1 vCPU, ~4 GiB)"]
        A -->|copy compose, nginx, configs,<br/>render .env files from Vault| D[/opt/awesome-localstack/]
        D -->|docker compose up| S[awesome-server stack]
        A -->|verify role| S
    end
    H[Hosting provider HTTPS proxy] --> E[edge :80] --> G[gateway 127.0.0.1:8080] --> S
```
