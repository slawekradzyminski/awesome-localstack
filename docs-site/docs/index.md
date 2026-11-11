---
title: Home
---

# Awesome LocalStack Wiki

Awesome Testing is a **training e-commerce platform**: a small but realistic shop
whose only purpose is to be tested. Students practise UI, API, contract,
performance, security and AI-assisted testing against it, locally with Docker
Compose or on the public deployments.

This wiki explains how every part works — the services and how they talk to
each other, the business rules behind each feature, and how the stack is run
and deployed — so you can design meaningful tests instead of guessing.

<div class="grid cards" markdown>

-   :material-sitemap: **[Architecture](architecture/index.md)**

    Services, ports, Compose profiles, gateway routing, authentication and
    service-to-service trust.

-   :material-cart-outline: **[Business flows](flows/index.md)**

    Sign-up to delivery: cart, checkout, payments, fulfilment, tracking,
    returns, emails and webhooks, with sequence and state diagrams.

-   :material-server: **[Operations](operations/index.md)**

    Running each profile locally, API explorers, production deployment with
    Ansible, monitoring, backups and troubleshooting.

-   :material-test-tube: **[For testers](testers/index.md)**

    Interesting test scenarios per feature: boundaries, race conditions,
    idempotency, failure injection and security checks.

</div>

## The platform in one picture

```mermaid
flowchart TB
    U[Browser / test tool] --> G[Gateway nginx]
    G -->|/| F[Frontend SPA]
    G -->|/api/v1/...| B[Backend]
    G -->|warehouse, returns,<br/>purchasing, tracking| W[warehouse-service]
    G -->|payments| P[payment-service]
    G -->|/docs/| D[This wiki]
    W -->|/internal/v1 + service token| B
    P -->|/internal/v1 + service token<br/>signed results| B
    B -->|refunds| P
    B --> DB[(PostgreSQL)]
    W -->|schema warehouse| DB
    P -->|schema payment| DB
    B -->|JMS| MQ[ActiveMQ Artemis] --> C[Email consumer] --> M[Mailpit]
    B --> L[LLM: ollama-mock or Docker Model Runner]
```

## Where it runs

| Environment | URL | Notes |
| --- | --- | --- |
| Lightweight profile (local) | `http://localhost:8081/` | Everyday local stack; data resets on recreate |
| Full profile (local) | `http://localhost:8081/` | Adds monitoring, ActiveMQ, email consumer, Mailpit, a real local LLM |
| Stable public playground | `https://awesome.byst.re/` | Production; no demo users, bootstrap catalog only |
| Disposable sandbox | `https://aitesters.byst.re/` | Separate database, reset every night |
| This wiki | `/docs/` on every gateway above | Built from `docs-site/` in `awesome-localstack` |

!!! tip "New here?"
    Start with [Running locally](operations/running-locally.md), sign in as
    `client` / `client`, then follow the [end-to-end order journey](flows/index.md#the-order-journey).

## Versions documented

This wiki describes the **commerce wave 3** release set: backend 3.15.0,
warehouse-service 1.2.0, payment-service 1.0.0, frontend 3.12.0 and consumer
3.6.0. The Compose files pin the exact images; see
[Releases and image pinning](operations/releases.md) for the current state of
the pins.
