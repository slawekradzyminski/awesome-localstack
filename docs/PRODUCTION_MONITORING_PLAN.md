# Production monitoring and resource-protection plan

## Status

This document is both the implementation plan and its rollout record.

| Phase | Status |
| --- | --- |
| Phase 1: JVM and container limits | Implemented and deployed |
| Phase 2: host/container visibility | Implemented and deployed |
| Phase 3: Telegram notification delivery | Implemented and deployed |
| Phase 4: public-path synthetic checks | Implemented and deployed |
| Phase 4b: independent host-down heartbeat | Deferred; off-server provider required |
| Phase 5: additional safeguards | Observability deployed; emergency swap blocked by LXC |

Phases 1 and 2 add no alert notifications by themselves. They establish bounded
JVMs, durable metrics, and dashboards so that phase 3 can add rules and
Telegram delivery against trustworthy data.

The production rollout completed on 2026-07-26 through the normal Ansible
deployment workflow. The encrypted pre-deploy PostgreSQL backup succeeded, all
47 deployment verification tasks passed, all four Prometheus scrape jobs were
healthy, and both the direct and public application routes returned HTTP 200.
The effective JVM maximum heaps were approximately 866 MiB for the backend and
742 MiB for the consumer. The first post-deploy snapshot reported approximately
2.0 GiB available RAM, up from approximately 1.0 GiB before the bounded JVMs
were restarted.

Phase 3 was deployed on 2026-07-26 with Alertmanager `v0.32.1`, five healthy
Prometheus scrape jobs, and 30 healthy alert rules. The Ansible deployment
completed with 66 successful tasks and no failures. Controlled warning and
critical alerts produced two firing and two resolved Telegram notifications;
Alertmanager reported four successful Telegram notifications and zero
notification failures. No synthetic or production alert remained active after
the test.

The phase 4/5 rollout completed on 2026-07-26 with 70 successful Ansible tasks
and no failures. Seven Prometheus jobs were healthy, both public probes returned
HTTP 200, 38 alert rules loaded, and no alert remained active. The observed
probe durations were approximately 0.20-0.29 seconds and the certificate had
approximately 36.9 days remaining. A direct negative probe against a reserved
invalid domain returned `probe_success 0` without changing a production scrape
target. Blackbox Exporter ran as UID/GID 65534 with a read-only root filesystem,
a 64 MiB memory limit, and no published port.

The same rollout proved that the MIKR.US host is an LXC container which rejects
`swapon` with `EPERM`. Deployment stopped before changing the application
stack; the newly created swap file and live `/etc/fstab` entry were removed.
The successful retry then skipped swap explicitly and deployed all remaining
phase 4/5 observability changes.

On 2026-07-26, `HostMemoryFullStallsCritical` exposed an LXC metric-scope
problem. Node Exporter's `/proc/pressure/memory` and `/proc/vmstat` counters
belong to the shared physical provider host, while `MemAvailable` is
virtualized by LXCFS for the VPS. At the incident peak, provider-host full PSI
reached approximately 19.6%, but VPS-root cgroup PSI remained effectively zero,
available VPS memory stayed above 42%, no local OOM occurred, and both public
probes remained healthy. Host memory PSI and OOM rules now use cAdvisor's
VPS-root cgroup series (`id="/"`). Provider-host PSI remains visible only as
diagnostic context in Grafana.

The follow-up resource-protection deployment completed with 69 successful
Ansible tasks and no failures. Every production container now has an explicit
memory limit. ActiveMQ started with a 512 MiB maximum heap instead of 2 GiB,
and Ollama Mock started with a 256 MiB maximum heap instead of approximately
29 GiB. Immediately after the stack settled, `MemAvailable` was approximately
2.3 GiB, aggregate container working sets were approximately 2.1 GiB,
VPS-root PSI was zero, all VPS-local memory rules were inactive, and the direct,
local-gateway, and public HTTPS routes returned HTTP 200.

The remaining program-level acceptance gaps are the deliberately off-server
items: an independent public-route check, a missed-heartbeat notification, and
the isolated disposable-container OOM alert test. The on-VPS probes and
Telegram pipeline are deployed, but they are not described as substitutes for
those tests.

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
| Alertmanager | `v0.32.1` | `sha256:51a825c2a40acc3e338fdd00d622e01ec090f72be2b3ea46be0839cd47a4d286` |
| Blackbox Exporter | `v0.28.0` | `sha256:e753ff9f3fc458d02cca5eddab5a77e1c175eee484a8925ac7d524f04366c2fc` |

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

- MIKR.US plan: Mikrus 3.5 LXC with 4,352 MiB RAM and 45 GB disk.
- Installed RAM: approximately 4.25 GiB.
- Linux `MemAvailable`: approximately 1.0 GiB, or 23%.
- Availability-based memory use: approximately 77%.
- Provider-style cgroup use, including reclaimable cache: approximately 98%.
- Filesystem cache: approximately 845 MiB.
- Swap: not configured.
- Root filesystem: approximately 48% used, with 23 GiB available.
- Recent VPS-root cgroup memory pressure: zero at the time of inspection.
- VPS-root and container OOM events: none observed.
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

Phase 2 added Node Exporter and cAdvisor as private Prometheus targets. Prometheus
stores data in a named volume with both a 30-day time limit and a 5 GB size
limit. Grafana provisions the `Production Resources` dashboard. The available
`sysstat` files did not contain usable current-host history.

Phase 3 added private, persistent Alertmanager storage, Vault-rendered Telegram
credentials, host/container/JVM/service alert rules, grouped firing and
resolved notifications, and deployment verification for rules, discovery,
binary revision, and secret permissions.

Phase 4 added a private Blackbox Exporter which probes the public login and
OpenAPI routes every 30 seconds through public DNS with certificate validation.
Prometheus records success, HTTP status, latency phases, and TLS expiry, then
routes sustained failures through the existing Telegram receiver. Because the
probe runs on the monitored VPS, this is public-path synthetic monitoring, not
independent host-down detection.

Phase 5 added a guarded Ansible role for a 1 GiB swap file with
`vm.swappiness=10`, swap occupancy and paging alerts, and a Grafana dashboard
for swap, PSI, public availability, latency, and TLS lifetime. A production
activation attempt on 2026-07-26 proved that the MIKR.US LXC layer rejects
`swapon` with `EPERM`. The newly created file and `/etc/fstab` entry were
removed immediately, and production keeps `swap_enabled: false` with the reason
tracked in inventory. The role remains ready for a future VM or package that
grants swap capability.

## Target architecture

The deployed monitoring path, plus the explicitly deferred external path, is:

```text
Node Exporter -----\
cAdvisor -----------+--> Prometheus --> Alertmanager --> Telegram Bot API --> operator
Spring Actuator ----/
Blackbox Exporter --/

[Future] External monitor --> public HTTPS endpoints and VPS heartbeat --> operator notification
```

The exporters, Prometheus, and Alertmanager must remain private. They should be
reachable only through the Docker network or VPS loopback, not through a public
port.

### Node Exporter

Node Exporter collects:

- `MemAvailable` and total RAM;
- swap use and paging;
- filesystem capacity and inode availability;
- CPU, load, network, and host uptime.

On MIKR.US LXC, Node Exporter's pressure and VM OOM counters describe the
shared provider host rather than this VPS. They must not drive VPS paging
alerts. The provider-host PSI series may be retained for noisy-neighbor
diagnostics only.

### cAdvisor

cAdvisor collects:

- per-container working-set memory;
- configured container memory limits;
- per-container OOM events;
- VPS-root cgroup memory PSI and OOM events through the `id="/"` series;
- CPU use and throttling;
- container last-seen state.

Container labels should be restricted to the labels needed for alerting. Avoid
exporting environment variables or high-cardinality metadata.

### Blackbox Exporter

Use an internal Blackbox Exporter to check the application through public DNS,
TLS, and the edge gateway. An independent external monitor is still required
because an on-server probe cannot detect loss of the whole VPS or its public
network.

## Alert delivery

The deployed phase 3 receiver is a private Telegram bot. Alertmanager reads the
bot token and chat ID from files rendered by Ansible from Vault, groups related
alerts, and sends firing and resolved notifications without exposing a
monitoring port publicly.

Telegram was selected because it does not require an SMTP mailbox or
application password. The bot token must be treated as a credential: it is
absent from Git and Compose output, stored only in Ansible Vault locally, and
rendered on the VPS as a container-readable `0400` file.

Email remains a compatible optional receiver. Alertmanager can send alerts
directly through a real SMTP server without changing the Prometheus rules.

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
subjects, grouping, and repetition intervals.

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
```

The SMTP password must not be committed. Store it in Ansible Vault, render it
as a root-readable file on the VPS, and mount that file read-only into the
Alertmanager container. Non-secret SMTP settings may also be managed through
Ansible variables so the generated configuration stays environment-specific.

Telegram delivery from the VPS does not protect against complete VPS failure.
An external heartbeat monitor must therefore send its own notification
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
rate(container_pressure_memory_waiting_seconds_total{job="cadvisor",id="/"}[5m]) > 0.10
```

```promql
rate(container_pressure_memory_stalled_seconds_total{job="cadvisor",id="/"}[5m]) > 0.05
```

```promql
increase(container_oom_events_total{job="cadvisor",id="/"}[5m]) > 0
```

Do not substitute the similarly named Node Exporter pressure or VM OOM
counters on MIKR.US LXC; those series cover the shared physical provider host.

### Swap

The deployed swap policy is:

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

The production values below were selected after reviewing seven days of
working-set and RSS peaks. They are safety ceilings, not reservations, and
must be reviewed after controlled load tests or material traffic growth:

| Service | JVM target | Container limit |
| --- | --- | --- |
| `backend` | `-Xms256m -Xmx896m` | 1.5 GiB |
| `consumer` | `-Xms192m -Xmx768m` | 1.125 GiB |
| `aitesters-backend` | Existing percentage-based limit | Existing 768 MiB |
| `activemq` | `-Xms256M -Xmx512M` | 768 MiB |
| `ollama-mock` | `-Xms64m -Xmx256m` | 512 MiB |
| `grafana` | Not applicable | 640 MiB |
| `prometheus` | Not applicable | 512 MiB |
| `postgres` | Not applicable | 512 MiB |
| `gateway`, `edge` | Not applicable | 128 MiB each |
| frontends, `mailpit` | Not applicable | 64 MiB each |

The ActiveMQ image previously started with `-Xms512M -Xmx2G`; its explicit
Compose `JAVA_ARGS` now preserves the image's operational JVM properties while
bounding the heap. Ollama Mock previously advertised an approximately 29 GiB
maximum heap and is now explicitly bounded. Container limits leave room for
native allocations beyond the Java heap. Monitor after-GC heap, working set,
GC overhead, and OOM counters before tightening them further.

### Emergency swap

Create a 1 GiB swap file only if the VPS environment permits it. Configure low
swappiness so swap acts as a short-spike safety buffer rather than normal
working memory. Alert on both occupancy and paging activity.

The current MIKR.US LXC environment does not permit `swapon`, even for a valid
root-owned swap file on ext4. Do not retain an inactive swap file or
`/etc/fstab` entry on this host. Re-enable the tracked Ansible setting only
after a provider or package change supplies the required capability.

### Capacity upgrade

The current Mikrus 3.5 plan provides 4 GiB advertised RAM and 40 GB advertised
disk (4,352 MiB and 45 GB in the panel). An immediate upgrade is deferred
because the corrected VPS-local signals show healthy headroom after the JVM and
container limits were deployed. Observe at least seven days of normal traffic
before reconsidering capacity.

Reconsider migration when any of these conditions occurs:

- `MemAvailable` remains below 600 MiB or 15% for 10 minutes;
- VPS-root full memory PSI repeatedly exceeds 2% for 5 minutes;
- a production container remains above 85% of its limit;
- the VPS-root or a production container reports an OOM event; or
- expected traffic growth requires materially more CPU, IOPS, or memory.

If capacity is required, the preferred next plan is Mikrus 4.1 PRO: 8 GiB RAM,
80 GB disk, and doubled CPU and IOPS allocation. MIKR.US requires an operator
ticket for the in-place migration; migration is free and the remaining
subscription term is recalculated proportionally against the new plan price.
Treat the ticket and resulting migration window as an external change requiring
explicit approval and post-migration verification.

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

The on-VPS Blackbox Exporter monitors:

- `https://awesome.byst.re/login`;
- `https://awesome.byst.re/v3/api-docs`.

The VPS should eventually send a heartbeat every minute to a separate external
endpoint. Missing heartbeats for five minutes must generate an off-server
notification independently of Prometheus and Alertmanager.

A scheduled GitHub-hosted Actions workflow is intentionally not used. In a
private repository, a five-minute workflow would start about 8,640 jobs per
30-day month and each job is rounded up to a billable minute. This exceeds the
2,000 monthly minutes included with GitHub Free. A self-hosted Actions runner
would avoid runner charges but would fail with the same VPS and therefore add
no independence.

k6 is also intentionally not used as the continuous availability prober. k6 is
kept for bounded load and browser-journey tests; its Prometheus remote-write
output is experimental and a permanent k6 process would consume more resources
than Blackbox Exporter for simple HTTP/DNS/TLS probes.

The deployed on-VPS probes cover:

- DNS;
- TLS;
- the edge proxy; and
- the application routes.

The future off-server heartbeat is what will additionally cover complete VPS,
hosting-network, Prometheus, Alertmanager, and outbound Telegram failure.

## Repository implementation outline

Implemented repository changes:

1. Add Node Exporter, cAdvisor, Alertmanager, and Blackbox Exporter
   to `docker-compose.server.yml`.
2. Add the new Prometheus scrape jobs, `rule_files`, and Alertmanager target to
   `prometheus/prometheus.server.yml`.
3. Add rule groups under `prometheus/rules/`, separated into host, container,
   JVM, disk, and service files.
4. Add an Alertmanager configuration and notification templates.
5. Add Telegram bot and chat values to the Ansible Vault example.
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

Prometheus, Alertmanager, and Blackbox Exporter configurations must be
validated with their respective validation tools before deployment.

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
2. Configure a Telegram bot token and chat ID using Vault-managed credentials.
3. Add warning, critical, and resolved Telegram notifications.
4. Send a synthetic test alert and verify delivery and resolution.

### Phase 4: public-path synthetic checks

1. Deploy Blackbox Exporter as a private server-profile service.
2. Probe the public login and OpenAPI routes every 30 seconds.
3. Record DNS, TLS, HTTP status, latency, and certificate lifetime in
   Prometheus and Grafana.
4. Alert through the existing Telegram receiver on sustained failure, latency,
   or certificate-expiry conditions.
5. Configure and test the independent VPS heartbeat only after an off-server
   provider is selected.

### Phase 5: additional safeguards

1. Attempt guarded emergency-swap activation and cleanly disable it when the
   LXC provider rejects `swapon`.
2. Observe swap and PSI metrics and retain occupancy/thrashing alerts for a
   future swap-capable host.
3. Consider the optional memory guard only after thresholds have been proven
   under real traffic; do not enable it merely to compensate for unavailable
   swap.

## Acceptance criteria

The full monitoring program is complete when:

- host, container, JVM, disk, and endpoint history is visible;
- a synthetic warning Telegram notification is delivered;
- a synthetic critical Telegram notification is delivered;
- a resolved Telegram notification is delivered;
- an OOM test in an isolated disposable container produces an alert without
  affecting production services;
- a public-route failure is detected externally;
- a missing heartbeat produces an off-server notification;
- no monitoring port is publicly exposed;
- Telegram credentials are absent from Git and Compose output;
- direct and public application routes remain healthy after deployment; and
- the operator has a documented response for every critical alert.

## References

- [Prometheus Node Exporter guide](https://prometheus.io/docs/guides/node-exporter/)
- [Prometheus alerting overview](https://prometheus.io/docs/alerting/latest/overview/)
- [Alertmanager configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [cAdvisor Prometheus metrics](https://github.com/google/cadvisor/blob/master/docs/storage/prometheus.md)
- [Prometheus multi-target exporter pattern](https://prometheus.io/docs/guides/multi-target-exporter/)
- [GitHub Actions included usage](https://docs.github.com/en/billing/reference/product-usage-included)
- [GitHub Actions job-time billing](https://docs.github.com/en/actions/how-tos/monitor-workflows/view-job-execution-time)
- [k6 Prometheus remote write](https://grafana.com/docs/k6/latest/results-output/real-time/prometheus-remote-write/)
