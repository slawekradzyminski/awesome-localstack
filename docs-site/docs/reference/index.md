# Reference documents

These pages are the repository's own `docs/*.md` files, published unchanged
(edit them in `docs/`, not here). They are the detailed records behind the
wiki: contracts, runbooks and release history.

| Document | Topic |
| --- | --- |
| [Student guide](STUDENT_GUIDE.md) | Classroom walkthrough of the lightweight profile |
| [Profile URLs](PROFILE_URLS.md) | Every URL and port per profile, gateway route maps, rate limits |
| [Commerce features](COMMERCE_FULFILMENT.md) | What students can test in the commerce features, demo data |
| [Warehouse service contract](WAREHOUSE_SERVICE_CONTRACT.md) | Boundary between backend and warehouse-service, tracking addendum |
| [Payment service contract](PAYMENT_SERVICE_CONTRACT.md) | Boundary between backend and payment-service |
| [Event feed](EVENT_FEED.md) | The backend's pull feed of domain events and how the services consume it |
| [Architecture decisions](ARCHITECTURE_DECISIONS.md) | ADRs: pull event feed, fulfilment read model, per-service outboxes, one PostgreSQL server |
| [Webhooks](WEBHOOKS.md) | Payment result signatures and user webhooks |
| [SSO flow](SSO_FLOW.md), [Social login](SOCIAL_LOGIN.md), [Direct social login](DIRECT_SOCIAL_LOGIN.md) | Keycloak, OIDC and social identity brokering |
| [gRPC inventory](GRPC_INVENTORY.md), [gRPC training runbook](GRPC_TRAINING_RUNBOOK.md), [Protocol testing lab](PROTOCOL_TESTING_LAB.md) | REST, GraphQL and gRPC exercises |
| [Course compatibility](COURSE_COMPATIBILITY.md) | Running the frozen course suite against disposable backends |
| [Ansible](ANSIBLE.md), [SSH server](SSH_SERVER.md), [SSH tunnelling](SSH_TUNNELLING.md) | Production operations |
| [Container releases](CONTAINER_RELEASES.md) | Release history and the current compatibility set |
| [Production monitoring plan](PRODUCTION_MONITORING_PLAN.md), [Production backups](PRODUCTION_BACKUPS.md), [Production edge proxy](PRODUCTION_EDGE_PROXY.md) | Monitoring, backups and the edge |
