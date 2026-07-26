# Production monitoring and resource-protection plan

## Status

This document is both the implementation plan and its rollout record.

| Phase | Status |
| --- | --- |
| Phase 1: JVM and container limits | Implemented and deployed |
| Phase 2: host/container visibility | Implemented and deployed |
| Phase 3: notification delivery | Planned; waiting for SMTP configuration |
| Phase 4: independent outage detection | Planned |
| Phase 5: additional safeguards | Planned |

Phases 1 and 2 add no alert notifications by themselves. They establish bounded
JVMs, durable metrics, and dashboards so that phase 3 can add rules and email
delivery against trustworthy data.

The production rollout completed on 2026-07-26 through the normal Ansible
deployment workflow. The encrypted pre-deploy PostgreSQL backup succeeded, all
47 deployment verification tasks passed, all four Prometheus scrape jobs were
healthy, and both the direct and public application routes returned HTTP 200.
The effective JVM maximum heaps were approximately 866 MiB for the backend and
742 MiB for the consumer. The first post-deploy snapshot reported approximately
2.0 GiB available RAM, up from approximately 1.0 GiB before the bounded JVMs
were restarted.

### Monitoring image revision audit

The monitoring images were re-audited against their authoritative upstream
releases and registries on 2026-07-26. The Compose file uses exact stable tags
and immutable multi-architecture manifest digests rather than floating `latest`
tags.

| Component | Audited stable version | Immutable manifest digest |
| --- | --- | --- |
| Node Exporter | `v1.12.1` | `sha256:1b4e4438faca4dd7e001dd445d161a4a2091b0fededa84093b3a8dfeae1f1be0` |
| cAdvisor | `v0.60.5` | `sha256:763aecf1c32c2be8a1a75f9abfc2fc461005c9dbbaa39cb356b354aac1296dbe` |
| Prometheus | `v3.13.1` | `sha256:3c42b892cf723fa54d2f262c37a0e1f80aa8c8ddb1da7b9b0df9455a35a7f893` |
| Grafana | `13.1.1` | `sha256:7cb8c64c4d57a57e734073f3cc94620adb24a0acb929bd80ba9f14017e3a975b` |

Future audits must compare stable releases, review migration and security notes,
validate the exact registry manifest, and deploy through the normal backup and
verification workflow. A newer tag must not be adopted automatically without
these compatibility checks.

## Goal

Protect the production VPS from memory and disk exhaustion by:

1. limiting the damage a single service can cause;
2. collecting host, container, JVM, and endpoint metrics;
3. notifying an operator before the system reaches an OOM or disk-full state;
4. detecting complete VPS or network failure from outside the VPS; and
5. retaining enough history to distinguish a transient spike from a long-term
   capacity problem.

## Current baseline

The production VPS was inspected on 2026-07-26.

- Installed RAM: approximately 4.25 GiB.
- Linux `MemAvailable`: approximately 1.0 GiB, or 23%.
- Availability-based memory use: approximately 77%.
- Provider-style cgroup use, including reclaimable cache: approximately 98%.
- Filesystem cache: approximately 845 MiB.
- Swap: not configured.
- Root filesystem: approximately 48% used, with 23 GiB available.
- Recent Linux memory pressure: zero at the time of inspection.
- Kernel and container OOM events: none observed.
- All production containers were running and the direct and public backend
  checks returned HTTP 200.

The largest container memory users were the main backend, consumer, ActiveMQ,
AI testers backend, Ollama mock, and Grafana.

Before phase 1, the main backend and consumer JVMs both advertised a maximum heap of
approximately 29.7 GiB. This is much larger than the VPS and is possible
because those containers had neither an explicit JVM maximum heap nor a
container memory limit.

Phase 1 configures the backend with `-Xmx896m` inside a 1.5 GiB container and
the consumer with `-Xmx768m` inside a 1.125 GiB container.

Phase 2 adds Node Exporter and cAdvisor as private Prometheus targets. Prometheus
stores data in a named volume with both a 30-day time limit and a 5 GB size
limit. Grafana provisions the `Production Resources` dashboard. External
endpoint availability remains part of phase 4. The available `sysstat` files
do not contain usable current-host history.

## Target architecture

The proposed monitoring path is:

```text
Node Exporter -----\
cAdvisor -----------+--> Prometheus --> Alertmanager --> external SMTP --> operator email
Spring Actuator ----/
Blackbox Exporter --/

External monitor --> public HTTPS endpoints and VPS heartbeat --> operator email
```

The exporters, Prometheus, and Alertmanager must remain private. They should be
reachable only through the Docker network or VPS loopback, not through a public
port.

### Node Exporter

Add Node Exporter to collect:

- `MemAvailable` and total RAM;
- Linux PSI memory pressure;
- swap use and paging;
- kernel OOM counters;
- filesystem capacity and inode availability;
- CPU, load, network, and host uptime.

### cAdvisor

Add cAdvisor to collect:

- per-container working-set memory;
- configured container memory limits;
- per-container OOM events;
- CPU use and throttling;
- container last-seen state.

Container labels should be restricted to the labels needed for alerting. Avoid
exporting environment variables or high-cardinality metadata.

### Blackbox Exporter

Use an internal Blackbox Exporter to check the application through the gateway.
An independent external monitor must check the public routes because an
on-server probe cannot detect loss of the whole VPS or its public network.

## Alert delivery by email

Alertmanager can send alerts directly through a real SMTP server. Email can be
the initial and primary notification channel; Telegram or another immediate
channel can be added later without changing the Prometheus rules.

The existing Mailpit service must not be used as the production alert receiver.
It captures messages locally for testing and does not provide a reliable
off-server delivery path. It would also be unavailable during a VPS outage.

The production setup needs:

- an external SMTP server;
- a sender address;
- an SMTP username and password or provider-specific application password;
- a recipient address;
- TLS, normally STARTTLS on port 587 or implicit TLS on port 465.

Alertmanager supports multiple recipients, resolved notifications, custom
subjects, grouping, repetition intervals, and email threading.

An illustrative configuration is:

```yaml
global:
  smtp_smarthost: smtp.example.com:587
  smtp_from: alerts@example.com
  smtp_auth_username: alerts@example.com
  smtp_auth_password_file: /run/secrets/alertmanager-smtp-password
  smtp_require_tls: true

route:
  receiver: production-email
  group_by:
    - alertname
    - severity
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: production-email
    email_configs:
      - to: operator@example.com
        send_resolved: true
        headers:
          Subject: >-
            [{{ .Status | toUpper }}][{{ .CommonLabels.severity }}]
            {{ .CommonLabels.alertname }}
        threading:
          enabled: true
          thread_by_date: daily
```

The SMTP password must not be committed. Store it in Ansible Vault, render it
as a root-readable file on the VPS, and mount that file read-only into the
Alertmanager container. Non-secret SMTP settings may also be managed through
Ansible variables so the generated configuration stays environment-specific.

Email delivery from the VPS does not protect against complete VPS failure. An
external HTTP and heartbeat monitor must therefore send its own notification,
independently of the on-server Alertmanager.

## Alert policy

Alerts should use sustained conditions and Linux pressure indicators rather
than provider-style "used RAM" alone. This avoids alerting merely because Linux
is using otherwise idle memory as reclaimable filesystem cache.

### Host memory

| Alert | Warning | Critical |
| --- | --- | --- |
| Available memory | Below 15% for 10 minutes | Below 8% for 3 minutes |
| Absolute available memory | Below 600 MiB for 10 minutes | Below 300 MiB for 3 minutes |
| PSI memory waiting | Above 10% for 10 minutes | Above 20% for 3 minutes |
| PSI full stalls | Above 2% for 5 minutes | Above 5% for 3 minutes |
| Kernel OOM | Not applicable | Any new OOM kill |

Representative PromQL:

```promql
node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes < 0.15
```

```promql
rate(node_pressure_memory_waiting_seconds_total[5m]) > 0.10
```

```promql
rate(node_pressure_memory_stalled_seconds_total[5m]) > 0.05
```

```promql
increase(node_vmstat_oom_kill[5m]) > 0
```

### Swap

After swap is introduced:

- warning when more than 128 MiB is used for 10 minutes;
- critical when more than 50% is used;
- critical when sustained swap-in or swap-out activity indicates thrashing.

### Containers

| Alert | Warning | Critical |
| --- | --- | --- |
| Working set versus limit | Above 85% for 10 minutes | Above 95% for 2 minutes |
| Container OOM | Not applicable | Any new OOM event |
| Critical container missing | After 2 minutes | After 5 minutes |
| Unexpected growth | More than 25% over one hour | More than 40% over one hour |

The critical-service list should include at least:

- `backend`;
- `consumer`;
- `gateway`;
- `edge`;
- `postgres`;
- `activemq`.

### JVM

JVM percentage alerts are meaningful only after realistic maximum heaps have
been configured.

| Alert | Warning | Critical |
| --- | --- | --- |
| Heap after GC | Above 75% for 10 minutes | Above 90% for 5 minutes |
| GC overhead | Above 10% for 10 minutes | Above 20% for 5 minutes |
| Long GC pause | Workload-dependent threshold | Repeated severe pauses |
| Thread growth | Sustained abnormal increase | Limit-threatening increase |

### Disk

| Alert | Warning | Critical |
| --- | --- | --- |
| Available root filesystem | Below 20% | Below 10% |
| Available inodes | Below 15% | Below 8% |
| Forecasted exhaustion | Within 7 days | Within 48 hours |

Disk forecasting should require a minimum history window and should only fire
when current free space is also below a reasonable threshold. This prevents a
temporary image pull from producing a misleading linear forecast.

Automated cleanup must never run `docker volume prune`. Docker image cleanup
may be scheduled only with an age filter and after confirming that deployment
rollback requirements are preserved.

### Application and monitoring pipeline

Add alerts for:

- a Prometheus scrape target being unavailable;
- Prometheus rule-evaluation failures;
- Alertmanager notification failures;
- direct gateway health-check failure;
- public HTTPS health-check failure;
- TLS certificate expiry;
- a missed PostgreSQL backup;
- a failed PostgreSQL restore verification;
- a missing external heartbeat.

Alert inhibition should suppress dependent symptoms. For example, a confirmed
host-down alert should suppress individual container-down alerts.

## Active resource protection

### Explicit JVM and container limits

Use these as initial test values, not permanent values without observation:

| Service | Initial JVM target | Initial container limit |
| --- | --- | --- |
| `backend` | `-Xms256m -Xmx896m` | 1.5 GiB |
| `consumer` | `-Xms192m -Xmx768m` | 1.125 GiB |
| `aitesters-backend` | Existing percentage-based limit | Existing 768 MiB |
| `activemq` | 384-512 MiB maximum heap | 768 MiB |
| `ollama-mock` | Explicit heap if supported | 512 MiB |
| `grafana` | Not applicable | Approximately 640 MiB |
| `prometheus` | Not applicable | Approximately 384 MiB |

Validate the ActiveMQ and Ollama image-specific JVM options before changing
them. A container limit must leave room for native allocations beyond the Java
heap. Run controlled load tests and monitor after-GC heap, container working
set, GC overhead, and OOM counters before tightening a limit.

### Emergency swap

Create a 1 GiB swap file if the VPS environment permits it. Configure low
swappiness so swap acts as a short-spike safety buffer rather than normal
working memory. Alert on both occupancy and paging activity.

### Optional memory guard

After alerting and limits are stable, consider a systemd guard for last-resort
load shedding:

1. require both very low `MemAvailable` and sustained full PSI pressure;
2. send a notification;
3. stop only a pre-approved non-critical service;
4. never automatically stop PostgreSQL or the main backend;
5. prevent restart loops;
6. restore the sacrificed service only after a safe recovery period or manual
   approval.

Do not restart services based solely on a high provider-style RAM percentage.

## External checks

At minimum, monitor these public endpoints from outside the VPS:

- `https://awesome.byst.re/login`;
- `https://awesome.byst.re/v3/api-docs`.

The VPS should also send a heartbeat every minute to an external endpoint.
Missing heartbeats for five minutes should generate an email independently of
Prometheus and Alertmanager.

This covers failures of:

- the VPS;
- the hosting provider network;
- DNS;
- TLS;
- the edge proxy;
- Prometheus;
- Alertmanager;
- outbound SMTP from the VPS.

## Repository implementation outline

Expected repository changes:

1. Add Node Exporter, cAdvisor, Alertmanager, and optionally Blackbox Exporter
   to `docker-compose.server.yml`.
2. Add the new Prometheus scrape jobs, `rule_files`, and Alertmanager target to
   `prometheus/prometheus.server.yml`.
3. Add rule groups under `prometheus/rules/`, separated into host, container,
   JVM, disk, and service files.
4. Add an Alertmanager configuration template and notification templates.
5. Add SMTP and optional secondary-channel values to the Ansible inventory and
   Vault example.
6. Render secret files with restrictive permissions through Ansible.
7. Provision a host/container overview dashboard in Grafana.
8. Add Ansible verification for exporter targets, loaded rules, Alertmanager
   readiness, and both direct and public application routes.
9. Add operational documentation for testing, silencing, and responding to
   each alert.
10. Keep Compose profiles and deployment documentation synchronized.

Every modified Compose file must pass:

```bash
docker compose -f docker-compose.server.yml config --quiet
```

Prometheus and Alertmanager configurations must be validated with their
respective validation tools before deployment.

## Rollout order

### Phase 1: prevent a single-process takeover

1. Add explicit maximum heaps to the main backend and consumer.
2. Add matching container limits with native-memory headroom.
3. Deploy one change at a time.
4. Verify direct and public application routes.
5. Observe memory and JVM behavior.

### Phase 2: visibility

1. Deploy Node Exporter and cAdvisor.
2. Add host and container dashboards.
3. Retain enough Prometheus history for capacity analysis.

### Phase 3: notifications

1. Deploy Alertmanager.
2. Configure external SMTP using Vault-managed credentials.
3. Add warning, critical, and resolved email notifications.
4. Send a synthetic test alert and verify delivery and resolution.

### Phase 4: independent outage detection

1. Configure external public HTTP checks.
2. Configure the VPS heartbeat.
3. Test by temporarily disabling only the heartbeat sender.

### Phase 5: additional safeguards

1. Add emergency swap.
2. Observe swap and PSI metrics.
3. Consider the optional memory guard only after thresholds have been proven
   under real traffic.

## Acceptance criteria

The work is complete when:

- host, container, JVM, disk, and endpoint history is visible;
- a synthetic warning email is delivered;
- a synthetic critical email is delivered;
- a resolved email is delivered;
- an OOM test in an isolated disposable container produces an alert without
  affecting production services;
- a public-route failure is detected externally;
- a missing heartbeat produces an off-server email;
- no monitoring port is publicly exposed;
- SMTP credentials are absent from Git and Compose output;
- direct and public application routes remain healthy after deployment; and
- the operator has a documented response for every critical alert.

## References

- [Prometheus Node Exporter guide](https://prometheus.io/docs/guides/node-exporter/)
- [Prometheus alerting overview](https://prometheus.io/docs/alerting/latest/overview/)
- [Alertmanager configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [cAdvisor Prometheus metrics](https://github.com/google/cadvisor/blob/master/docs/storage/prometheus.md)
