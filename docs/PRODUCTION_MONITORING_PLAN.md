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
| Lean phase A: Grafana removed from production | Implemented in the repository; not yet deployed |
| Lean phase B: host watchdog and dead-man ping (replaces phase 4b) | Implemented in the repository; not yet deployed |
| Lean phase C: Prometheus stack removed from production | Planned follow-up |

The lean phases are described in
[Lean monitoring](#lean-monitoring-phases-a-b-and-c). The phase 1-5 records
below are historical: they mention Grafana, which lean phase A removes from
production.

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
diagnostic context (Grafana until lean phase A, now PromQL through
`make ansible-tunnel-prometheus`).

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
releases and registries on 2026-08-01. The Compose file uses exact stable tags
and immutable multi-architecture manifest digests rather than floating `latest`
tags.

| Component | Audited stable version | Immutable manifest digest |
| --- | --- | --- |
| Node Exporter | `v1.12.1` | `sha256:1b4e4438faca4dd7e001dd445d161a4a2091b0fededa84093b3a8dfeae1f1be0` |
| cAdvisor | `v0.60.5` | `sha256:763aecf1c32c2be8a1a75f9abfc2fc461005c9dbbaa39cb356b354aac1296dbe` |
| Prometheus | `v3.13.2` | `sha256:508729e0e2d18e11fd742a5a5ca70e557b940a93948c3c95fd0123a6fd538b69` |
| Grafana | `13.1.1` | `sha256:7cb8c64c4d57a57e734073f3cc94620adb24a0acb929bd80ba9f14017e3a975b` |
| Alertmanager | `v0.32.1` | `sha256:51a825c2a40acc3e338fdd00d622e01ec090f72be2b3ea46be0839cd47a4d286` |
| Blackbox Exporter | `v0.28.0` | `sha256:e753ff9f3fc458d02cca5eddab5a77e1c175eee484a8925ac7d524f04366c2fc` |

Future audits must compare stable releases, review migration and security notes,
validate the exact registry manifest, and deploy through the normal backup and
verification workflow. A newer tag must not be adopted automatically without
these compatibility checks.

## Lean monitoring (phases A, B and C)

The November 2026 review (owner's research note, 2026-11-11) found that the
on-box stack used about 850-900 MiB of the 4.25 GiB VPS for four alerts the
owner actually needs: site down, container unhealthy or OOM-killed, disk
filling, backup failed. Grafana alone used about 450 MiB (640 MiB limit) for
dashboards nobody opened, backups were never alerted, `aitesters.byst.re` was
not probed and nothing off-box could report the VPS itself being down. The
replacement runs in three phases; A and B are in the repository, C is planned.

| Lean phase | Status |
| --- | --- |
| A: remove Grafana from production | Implemented in the repository; not yet deployed |
| B: host watchdog, healthchecks, backup alerts, aitesters probes | Implemented in the repository; not yet deployed; 1-2 week parallel run pending |
| C: remove Prometheus, Alertmanager, cAdvisor and exporters | Planned follow-up (prerequisites below) |

### Phase A: Grafana removed

- `docker-compose.server.yml` no longer runs `grafana`; the deploy's
  `remove_orphans` removes the old container. Prometheus, Alertmanager,
  cAdvisor, Node Exporter, Blackbox Exporter and every Telegram alert are
  unchanged.
- Ansible no longer copies `grafana/` (the `app` role deletes the old copy on
  the server), `.env.runtime` no longer carries `GF_SECURITY_ADMIN_PASSWORD`,
  the `verify` role no longer checks the two dashboards, and
  `vault.yml.example` no longer lists `grafana_admin_password` (an existing
  value in the real Vault is now unused and can be deleted at leisure).
- `make ansible-tunnel-grafana` became `make ansible-tunnel-prometheus`:
  Prometheus now publishes on the VPS loopback only (`127.0.0.1:9090`), and its
  UI answers PromQL and lists firing alerts.
- `grafana/server-provisioning/` and the production-only safeguards dashboard
  are deleted; the resources dashboard became the local **Container
  Resources** dashboard of the monitoring overlay.
- Memory: about 450 MiB of working set and a 640 MiB limit are freed (the
  long-running limits drop from about 5.8 GiB to about 5.2 GiB).
- First deploy: changing `.env.runtime` recreates the services that read it
  (backend, consumer, activemq, postgres) once, inside the usual deployment
  silence and watchdog pause. Rollback is `git revert` and a deploy.

### Phase B: host watchdog

`ansible/roles/watchdog` installs `/usr/local/sbin/awesome-watchdog` (Python
standard library only), `/etc/awesome-watchdog/config.json` (mode 0600,
rendered from Vault), `awesome-watchdog.timer` (every minute) and the
`awesome-watchdog-notify@.service` template. It runs early in `deploy.yml`
(after `swap`, before `postgres_backup` and the deployment silence). It keeps
no resident process and sends to the **same bot and chat as Alertmanager**
(`alertmanager_telegram_bot_token`, `alertmanager_telegram_chat_id`).

| Check | Source | Reported when | Confirmation |
| --- | --- | --- | --- |
| Container missing | `docker ps`/`inspect`, project `awesome-server`; expected set = every service of `docker-compose.server.yml` except the one-shots | no container for an expected service | 2 runs |
| Container exited, dead, paused, restarting | `State.Status`, exit code, `OOMKilled` | not `running` | 2 runs |
| Container unhealthy | `State.Health` (Docker healthchecks below) | `unhealthy` | 3 runs |
| Restart loop | `RestartCount` of the same container ID | increased within 10 minutes | 1 run |
| One-shot failed | `postgres-roles`, `aitesters-postgres-roles` | exited non-zero | 1 run |
| Consumer health | `curl http://consumer:4002/actuator/health` from the gateway container | request fails | 2 runs |
| OOM kill (event) | `docker events --filter event=oom` since the previous run | each event | immediate |
| OOM kill (kernel) | `/sys/fs/cgroup/memory.events` `oom_kill` (VPS-root cgroup) and each container's cgroup `memory.events` | counter increased | immediate |
| Disk | `statvfs /` | 85% and 90% used (one problem per threshold) | 1 run |
| Inodes | `statvfs /` | 92% used | 1 run |
| Memory | `MemAvailable` (LXCFS-virtualized, VPS-scoped) | below 300 MiB | 10 runs |
| Backup stale | newest `*.sql.gz.enc` in `/var/backups/awesome-localstack/postgres/daily` | older than 26 h, or none | 1 run |
| Restore check stale | `restore-check.ok` stamp written by a successful restore check | older than 8 days | 1 run |
| Backup or restore check failed | `OnFailure=awesome-watchdog-notify@%n.service` on both units | unit failed (result and last log lines) | immediate |
| Watchdog cannot check | Docker CLI or `/proc` unreadable | check error | 2 runs |

Thresholds match `prometheus/rules/host.yml` for the parallel run.

**De-duplication.** `/var/lib/awesome-watchdog/state.json` remembers each
problem. A problem is sent once when it reaches its confirmation count
(`PROBLEM:`), never repeated while it persists (`watchdog_repeat_hours: 0`;
set N to repeat every N hours), and its recovery is sent once (`RESOLVED:`).
A problem that disappears before confirmation is forgotten silently. Events
(`EVENT:`) are sent once. All lines of one run go in one message. If Telegram
delivery fails, nothing is marked as sent and the next run retries.

**Deployments and resets.** The `deployment_silence` role now also runs
`awesome-watchdog maintenance start --minutes 15` before `app` and
`maintenance stop` after a successful `verify`. A pause suspends only the
container and consumer checks (known container problems are frozen, not
resolved); OOM, disk, memory and backup checks continue, and the script
ignores any pause older than 30 minutes, so a failed deployment cannot mute it.
The nightly aitesters reset recreates its containers in seconds, below the
two-run confirmation.

**Dead-man ping.** When `watchdog_healthcheck_url` is set (Vault), every run
POSTs to it and a run with a check error or a failed Telegram delivery posts to
`<url>/fail`. An external service such as Healthchecks.io then alerts from
outside when pings stop: VPS down, network down, timer stopped or the script
broken. Empty (the default) disables the ping.

**OOM sources on the MIKR.US LXC host.** The watchdog reads all three and
de-duplicates a container's cgroup OOM against its Docker event:

1. Docker `oom` events are emitted by containerd for container cgroups and
   need no host access; they work on any Docker host (proven locally on Docker
   Desktop with a 12 MiB container).
2. `/sys/fs/cgroup/memory.events` inside the LXC is the VPS's own cgroup
   (cgroup namespace root), the same cgroup cAdvisor reports as `id="/"`; its
   hierarchical `oom_kill` also counts kills outside containers, which Docker
   events cannot see. The current `HostKernelOOMKill` rule already depends on
   this cgroup, so it is expected to be readable.
3. Per-container `memory.events` is found through `/proc/<pid>/cgroup`.

Each deploy's `verify` prints `awesome-watchdog diagnose`, which states which
sources are readable. Record the first production result here:

| Source | Readable on production | Proven by the OOM test |
| --- | --- | --- |
| Docker `oom` events | to be recorded after the first deploy | |
| VPS-root `memory.events` | to be recorded after the first deploy | |
| Container `memory.events` | to be recorded after the first deploy | |

**Healthchecks.** Every long-running server service now has one, except the
consumer, which is a distroless native image with neither shell nor curl
(the watchdog probes it instead):

| Service | Probe |
| --- | --- |
| `backend`, `aitesters-backend` | bash `/dev/tcp` GET `/actuator/health` (same as the image's own `HEALTHCHECK`, now explicit) |
| `frontend`, `aitesters-frontend` | `curl http://127.0.0.1/` |
| `gateway` | `curl http://127.0.0.1/images/iphone.png` (a static file, so no upstream decides the gateway's health) |
| `edge` | the same file through the edge with `Host: awesome.byst.re` (the edge's job is that hop) |
| `activemq` | bash `/dev/tcp` connect to `61616` (no curl in the image), 90 s start period |

`start_interval: 2s` (3 s for ActiveMQ) makes a fresh container healthy within
seconds, so `docker compose up --wait` does not slow deploys. Dependencies:
`edge` waits for a healthy `gateway`, `consumer` for a healthy `activemq`; the
gateway keeps `service_started` for `aitesters-backend` (the stable site must
not wait for the sandbox) and the backend keeps `service_started` for
`activemq`.

**Probes.** The `public_https` Blackbox job also probes
`https://aitesters.byst.re/login` and `https://aitesters.byst.re/v3/api-docs`
(same `public-edge` service label, so the deployment silence covers them);
`verify` expects six probe results.

**Contract and tests.** `scripts/verify-production-monitoring.py` (CI job
`verifyProductionMonitoring`) checks the Grafana removal, the healthchecks and
dependency conditions, the aitesters probes, the watchdog role, units and
deploy ordering, the backup `OnFailure=` hooks and the deployment pause.
`scripts/verify-watchdog.py` tests the script against a fake Docker CLI, fake
cgroup and `/proc` trees and a fake Telegram and ping endpoint.
`scripts/verify-postgres-restore.py` also requires the restore-check stamp.

#### Owner's manual steps

1. **Dead-man check.** Create an account and a check at Healthchecks.io (or any
   service that alerts on missed HTTP pings): period 1 minute, grace 5 minutes,
   with its Telegram integration pointing at the same chat. Its free tier is for
   hobby, open-source and non-profit use; paid trainings may need a paid plan.
   Put the ping URL into Vault as `watchdog_healthcheck_url` (`make
   ansible-edit-vault`) and deploy. Nobody has created this account yet.
2. **External HTTP check.** Add an off-box uptime monitor (Healthchecks.io
   cannot do HTTP checks; UptimeRobot Free can, with e-mail alerts) for
   `https://awesome.byst.re/login` and `https://aitesters.byst.re/login`. Until
   phase C, Blackbox Exporter covers TLS expiry from the VPS.
3. Optionally delete `grafana_admin_password` from the real Vault.

#### Parallel-run checklist (1-2 weeks before phase C)

Run each item once after the first deploy, on the VPS as root in
`/opt/awesome-localstack`, and record the date. `W=/usr/local/sbin/awesome-watchdog`.
For threshold items, a test copy of the configuration with its own state file
proves the alert path without filling the disk:

```bash
python3 - <<'PY'
import json
config = json.load(open("/etc/awesome-watchdog/config.json"))
config.update(state_file="/root/watchdog-test-state.json", healthcheck_url="",
              disk_used_percent_thresholds=[1], memory_available_min_mib=10**6,
              memory_confirm_runs=1, backup_max_age_hours=0)
json.dump(config, open("/root/watchdog-test.json", "w"))
PY
chmod 600 /root/watchdog-test.json
```

| # | Alert | Trigger | Expected Telegram | Clean-up | Done |
| --- | --- | --- | --- | --- | --- |
| 1 | Delivery | `$W test-message` | `TEST: watchdog Telegram delivery works` | none | |
| 2 | Container exited / missing | `docker compose -f docker-compose.server.yml stop aitesters-frontend` | `PROBLEM: Container aitesters-frontend is exited` after about 2 min | `... start aitesters-frontend`; expect one `RESOLVED:` | |
| 3 | Container unhealthy | `docker compose -f docker-compose.server.yml exec aitesters-frontend mv /usr/share/nginx/html/index.html /tmp/` | `PROBLEM: Container aitesters-frontend is unhealthy` after about 4-5 min | `... exec aitesters-frontend mv /tmp/index.html /usr/share/nginx/html/`; one `RESOLVED:` | |
| 4 | Restart loop | `docker compose -f docker-compose.server.yml exec aitesters-frontend nginx -s quit` | `PROBLEM: Container aitesters-frontend restarted in the last 10 minutes` | resolves by itself after 10 min | |
| 5 | OOM kill | `docker run --rm -m 16m --memory-swap 16m --entrypoint sh <postgres_restore_image> -c 'x=a; while :; do x=$x$x; done'` | `EVENT: OOM kill in container ...` and, if the VPS-root cgroup is readable, `EVENT: Kernel OOM killer ran ...`; Alertmanager's `ContainerOOMEvent` too | none (container is removed); record the result in the OOM-source table | |
| 6 | Disk, memory, backup stale | `AWESOME_WATCHDOG_CONFIG=/root/watchdog-test.json $W run` | `PROBLEM: Disk / is ...`, `Available memory ...`, `Newest PostgreSQL backup is ...` | `rm /root/watchdog-test.json /root/watchdog-test-state.json` | |
| 7 | Backup unit failure | `systemd-run --unit=watchdog-onfailure-test -p OnFailure=awesome-watchdog-notify@%n.service /bin/false` | `FAILED: systemd unit watchdog-onfailure-test.service failed` | `systemctl reset-failed watchdog-onfailure-test.service` | |
| 8 | Dead-man | after manual step 1: `systemctl stop awesome-watchdog.timer` | Healthchecks.io alert after period + grace | `systemctl start awesome-watchdog.timer` | |
| 9 | Deploy stays quiet | a normal `make ansible-deploy` | no watchdog container messages; `verify` prints the dry run and `diagnose` | none | |
| 10 | aitesters probes | `make ansible-tunnel-prometheus`, query `probe_success{job="public_https"}` | six series, all `1` | none | |

During the parallel run, compare every Alertmanager Telegram message with the
watchdog's. Phase C may start only when the watchdog reported everything
Alertmanager did that the owner cares about.

### Phase C (planned follow-up): remove the Prometheus stack

Not part of this change. It frees roughly another 400-450 MiB (Prometheus
about 170 MiB, cAdvisor about 190 MiB, Alertmanager, Node Exporter and
Blackbox Exporter about 40-90 MiB together) and the scrape load on the single
shared vCPU.

Prerequisites:

- the parallel-run checklist above is complete, with no incident that only
  Alertmanager reported;
- the OOM-source table is filled in from production (`diagnose` plus test 5),
  so it is known whether kernel OOM kills outside containers are still seen
  without cAdvisor;
- the dead-man check (manual step 1) exists and test 8 passed;
- an external HTTP and TLS-expiry check replaces Blackbox Exporter (manual
  step 2, or a daily `openssl s_client` expiry check added to the watchdog);
- the owner accepts losing metric history, JVM heap and PSI signals, latency
  and the unseen warning tier (optionally keep an hourly `docker stats` and
  `df` line in a rotated log for capacity questions).

Planned work:

1. Remove `prometheus`, `alertmanager`, `cadvisor`, `node-exporter`,
   `blackbox-exporter` and the `prometheus-data` and `alertmanager-data`
   volumes from `docker-compose.server.yml`; delete
   `prometheus/prometheus.server.yml`, `prometheus/rules/`, `alertmanager/` and
   `blackbox/` (keep `prometheus/prometheus.yml` for the local overlay).
2. Replace the Alertmanager silence in `deployment_silence` with the watchdog
   pause alone, and rewrite `scripts/verify-deployment-silence.py` and the
   silence markers in `scripts/verify-backend-upgrade.py` to assert the same
   wrap-and-expire contract.
3. In `verify`, drop the monitoring endpoint, target, Alertmanager, rule,
   Blackbox and probe tasks; keep the watchdog timer, dry run and `diagnose`,
   and add a direct `curl` of the public URLs.
4. In `app`, drop the Prometheus and Alertmanager checksum, restart and
   secret-file tasks, keep the Telegram credential assert, and drop
   `prometheus_server_config_files` and `alertmanager_config_files` from
   `group_vars`.
5. Let the `cleanup` role remove the retired images and volumes; then update
   this plan, `README.md`, `docs/ANSIBLE.md`, `docs/SSH_SERVER.md`,
   `docs/SSH_TUNNELLING.md`, `docs/PROFILE_URLS.md`,
   `docs/PRODUCTION_BACKUPS.md` and the `docs-site` operations and
   architecture pages.

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

Phase 1 bounded those JVMs (backend `-Xmx896m` in 1.5 GiB, consumer `-Xmx768m`
in 1.125 GiB). Both now run as GraalVM native images with much smaller heaps
and limits; see [Explicit JVM and container limits](#explicit-jvm-and-container-limits).

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
alerts, and delivers notifications without exposing a monitoring port publicly.

Since 2026-11-09 delivery follows a low-noise policy, because this is a
training stack and an external uptime monitor already covers public
availability:

- only `severity="critical"` alerts reach Telegram; warnings go to the
  `dashboard-only` receiver and stay visible in Prometheus and the
  Alertmanager API;
- resolved notifications are not sent, and a still-firing critical repeats at
  most once every 24 hours;
- critical rules wait 10 to 15 minutes, so planned deploy restarts (the backend
  scrape and public probes fail for a few minutes) never page; scrape-target
  and public-probe criticals wait 15 minutes, matching the deploy silence;
- `PrometheusRuleEvaluationFailures` and `AlertmanagerNotificationFailures` are
  warnings, because a failing Telegram channel cannot report its own failure.

Immediate criticals remain only for kernel or container OOM events.

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
| Available memory | Below 15% for 10 minutes | Below 8% for 10 minutes |
| Absolute available memory | Below 600 MiB for 10 minutes | Below 300 MiB for 10 minutes |
| PSI memory waiting | Above 10% for 10 minutes | Above 20% for 15 minutes |
| PSI full stalls | Above 2% for 5 minutes | Above 5% for 10 minutes |
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
- critical when more than 50% is used for 10 minutes;
- critical when swap-in or swap-out activity indicates thrashing for 10 minutes.

### Containers

| Alert | Warning | Critical |
| --- | --- | --- |
| Working set versus limit | Above 85% for 10 minutes | Above 95% for 10 minutes |
| Container OOM | Not applicable | Any new OOM event |
| Critical container missing | Not applicable | After 15 minutes |
| Unexpected growth | More than 25% over one hour | More than 40% over one hour |

The critical-service list should include at least:

- `backend`;
- `consumer`;
- `warehouse-service`;
- `payment-service`;
- `notification-service`;
- `gateway`;
- `edge`;
- `postgres`;
- `activemq`.

### JVM

JVM percentage alerts are meaningful only after realistic maximum heaps have
been configured.

| Alert | Warning | Critical |
| --- | --- | --- |
| Heap after GC | Above 75% for 10 minutes | Above 90% for 15 minutes |
| GC overhead | Above 10% for 10 minutes | Above 20% for 15 minutes |
| Long GC pause | Workload-dependent threshold | Repeated severe pauses |
| Thread growth | Sustained abnormal increase | Limit-threatening increase |

### Disk

| Alert | Warning | Critical |
| --- | --- | --- |
| Available root filesystem | Below 20% for 10 minutes | Below 10% for 15 minutes |
| Available inodes | Below 15% for 10 minutes | Below 8% for 15 minutes |
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
| `backend` | `-Xmx384m` runtime argument (GraalVM native image since 3.13.0) | 640 MiB |
| `consumer` | `-Xmx64m` runtime argument (GraalVM native image since 3.5.0, ~70 MiB RSS measured) | 160 MiB |
| `aitesters-backend` | `-Xmx256m` runtime argument (GraalVM native image since 3.13.0) | 448 MiB |
| `warehouse-service`, `aitesters-warehouse-service` | `-Xmx64m` runtime argument (GraalVM native image, ~58 MiB RSS measured) | 160 MiB each |
| `payment-service`, `aitesters-payment-service` | `-Xmx64m` runtime argument (GraalVM native image, not yet measured in production) | 160 MiB each |
| `aitesters-postgres` | Not applicable (disk-backed sandbox database, `shared_buffers=32MB`) | 160 MiB |
| `activemq` | `-Xms256M -Xmx512M` | 768 MiB |
| `ollama-mock` | `-Xms64m -Xmx256m` | 512 MiB |
| `prometheus` | Not applicable | 512 MiB |
| `postgres` | Not applicable | 512 MiB |
| `gateway`, `edge` | Not applicable | 128 MiB each |
| frontends, `mailpit` | Not applicable | 64 MiB each |

Grafana (640 MiB) left production in lean phase A.

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
- `https://awesome.byst.re/v3/api-docs`;
- `https://awesome.byst.re/warehouse/v3/api-docs`;
- `https://awesome.byst.re/payment/v3/api-docs`;
- `https://awesome.byst.re/notification/v3/api-docs` (distributed-lab release);
- `https://aitesters.byst.re/login` and `https://aitesters.byst.re/v3/api-docs`
  (added in lean phase B).

payment-service is also scraped as `spring_payment_micrometer` and has its own
`CriticalContainerMissing` rule; the deployment silence covers its scrape
target while the stack converges. The two payment-services add up to 320 MiB of
container limits (about 120 MiB expected working set); see the memory budget
in [ANSIBLE.md](ANSIBLE.md#memory-budget). notification-service follows the
same pattern (`spring_notification_micrometer`, its own `CriticalContainerMissing`
rule, deployment silence, two 160 MiB containers).

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

The off-server heartbeat is the host watchdog's dead-man ping (lean phase B,
`watchdog_healthcheck_url`); once the owner creates the external check it
additionally covers complete VPS, hosting-network, watchdog and outbound
Telegram failure.

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

### CPU on the single shared vCPU

The Mikrus 3.5 VPS has one dynamically allocated vCPU; the provider may throttle
sustained full load. On 8 November 2026 the host idled around 26% busy and
saturated (CPU PSI waiting about 99%) during e2e suites and deployments. Spring
scrapes run every 15s, both backends run as GraalVM native images since 3.13.0
(no JIT warm-up after deploys or the nightly reset), and `HostCpuSaturated`
warns only when CPU PSI waiting stays above 90% for 30 minutes, so ordinary test
runs and deploys stay silent. The only upgrade that adds CPU is the PRO 4.1 plan
(2x CPU limit), which was out of stock; a back-in-stock alert is registered.
