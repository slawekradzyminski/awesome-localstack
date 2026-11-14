SHELL := /bin/zsh

.PHONY: ansible-galaxy ansible-bootstrap deploy-preflight ansible-deploy ansible-deploy-backend-upgrade ansible-verify ansible-cleanup ansible-reset-demo-state ansible-reset-aitesters-state ansible-ping ansible-ssh ansible-edit-vault ansible-tunnel-prometheus ansible-tunnel-mailpit ansible-tunnel-all ansible-tunnel-kill-prometheus ansible-tunnel-kill-mailpit ansible-tunnel-kill-all sync-release-images chaos-up chaos chaos-list chaos-status chaos-reset chaos-heal chaos-down tracing-up tracing-down

ANSIBLE_VAULT_FILE := .vault_pass

ansible-galaxy:
	cd ansible && ansible-galaxy collection install -r requirements.yml

ansible-ping:
	cd ansible && ansible production -m ping --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-ssh:
	eval "$$(cd ansible && ./resolve-ssh-vars.sh)" && ssh -o StrictHostKeyChecking=accept-new -p "$$SSH_PORT" -i "$$SSH_KEY_PATH" "$$SSH_USER@$$SSH_HOST"

ansible-bootstrap:
	cd ansible && ansible-playbook playbooks/bootstrap.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

# Local checks of what the deploy would otherwise discover on the server after
# it started changing it: the server Compose config and the strict docs image
# build. scripts/release-train.py deploy runs them itself and passes
# SKIP_DEPLOY_PREFLIGHT=1.
deploy-preflight:
	@if [[ "$(SKIP_DEPLOY_PREFLIGHT)" == 1 ]]; then echo "deploy preflight: already run"; else python3 scripts/release-train.py preflight; fi

ansible-deploy: deploy-preflight
	cd ansible && ansible-playbook playbooks/deploy.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-deploy-backend-upgrade: deploy-preflight
	cd ansible && ansible-playbook playbooks/deploy.yml --vault-password-file $(ANSIBLE_VAULT_FILE) -e backend_upgrade_quiesce=true

ansible-verify:
	cd ansible && ansible-playbook playbooks/verify.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-cleanup:
	cd ansible && ansible-playbook playbooks/cleanup.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

sync-release-images:
	python3 scripts/sync-workspace-release-images.py

ansible-reset-demo-state: deploy-preflight
	cd ansible && ansible-playbook playbooks/reset-demo-state.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-reset-aitesters-state:
	cd ansible && ansible-playbook playbooks/reset-aitesters-state.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-edit-vault:
	cd ansible && ansible-vault edit inventory/group_vars/production/vault.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

# Production has no Grafana (lean monitoring); the Prometheus UI answers PromQL
# and lists firing alerts on http://localhost:9090.
ansible-tunnel-prometheus:
	eval "$$(cd ansible && ./resolve-ssh-vars.sh)" && ssh -o StrictHostKeyChecking=accept-new -N -L 9090:127.0.0.1:9090 -p "$$SSH_PORT" -i "$$SSH_KEY_PATH" "$$SSH_USER@$$SSH_HOST"

ansible-tunnel-mailpit:
	eval "$$(cd ansible && ./resolve-ssh-vars.sh)" && ssh -o StrictHostKeyChecking=accept-new -N -L 8025:127.0.0.1:8025 -p "$$SSH_PORT" -i "$$SSH_KEY_PATH" "$$SSH_USER@$$SSH_HOST"

ansible-tunnel-all:
	eval "$$(cd ansible && ./resolve-ssh-vars.sh)" && ssh -o StrictHostKeyChecking=accept-new -N -L 9090:127.0.0.1:9090 -L 8025:127.0.0.1:8025 -p "$$SSH_PORT" -i "$$SSH_KEY_PATH" "$$SSH_USER@$$SSH_HOST"

ansible-tunnel-kill-prometheus:
	pkill -f 'ssh .*9090:127.0.0.1:9090' || true

ansible-tunnel-kill-mailpit:
	pkill -f 'ssh .*8025:127.0.0.1:8025' || true

ansible-tunnel-kill-all:
	pkill -f 'ssh .*9090:127.0.0.1:9090|ssh .*8025:127.0.0.1:8025' || true

# Fault-injection lab (docs/FAULT_INJECTION_LAB.md). PROFILE: lightweight (default
# when nothing runs) or full; WITH: extra overlays, e.g. WITH="tracing monitoring".
#   make chaos-up PROFILE=full
#   make chaos SCENARIO=backend-down TARGET=warehouse
#   make chaos SCENARIO=backend-slow VALUE=5000 TARGET=payment
chaos-up:
	@scripts/chaos up $(PROFILE) $(WITH)

chaos:
	@if [[ -z "$(SCENARIO)" ]]; then echo "usage: make chaos SCENARIO=<name> [VALUE=<number>] [TARGET=<service>]"; echo; scripts/chaos list; exit 2; fi
	@scripts/chaos $(SCENARIO) $(VALUE) $(TARGET)

chaos-list:
	@scripts/chaos list

chaos-status:
	@scripts/chaos status

chaos-reset chaos-heal:
	@scripts/chaos reset

chaos-down:
	@scripts/chaos down

# Jaeger (docker-compose.tracing.yml) on the running profile, keeping the chaos
# and monitoring overlays when they run. UI: http://127.0.0.1:16686
tracing-up:
	@scripts/tracing up $(PROFILE)

tracing-down:
	@scripts/tracing down $(PROFILE)
