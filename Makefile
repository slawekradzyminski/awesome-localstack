SHELL := /bin/zsh

.PHONY: ansible-galaxy ansible-bootstrap ansible-deploy ansible-verify ansible-reset-demo-state ansible-reset-aitesters-state ansible-ping ansible-ssh ansible-edit-vault ansible-tunnel-grafana ansible-tunnel-mailhog ansible-tunnel-all ansible-tunnel-kill-grafana ansible-tunnel-kill-mailhog ansible-tunnel-kill-all

ANSIBLE_VAULT_FILE := .vault_pass

ansible-galaxy:
	cd ansible && ansible-galaxy collection install -r requirements.yml

ansible-ping:
	cd ansible && ansible production -m ping --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-ssh:
	eval "$$(cd ansible && ./resolve-ssh-vars.sh)" && ssh -o StrictHostKeyChecking=accept-new -p "$$SSH_PORT" -i "$$SSH_KEY_PATH" "$$SSH_USER@$$SSH_HOST"

ansible-bootstrap:
	cd ansible && ansible-playbook playbooks/bootstrap.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-deploy:
	cd ansible && ansible-playbook playbooks/deploy.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-verify:
	cd ansible && ansible-playbook playbooks/verify.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-reset-demo-state:
	cd ansible && ansible-playbook playbooks/reset-demo-state.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-reset-aitesters-state:
	cd ansible && ansible-playbook playbooks/reset-aitesters-state.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-edit-vault:
	cd ansible && ansible-vault edit inventory/group_vars/production/vault.yml --vault-password-file $(ANSIBLE_VAULT_FILE)

ansible-tunnel-grafana:
	eval "$$(cd ansible && ./resolve-ssh-vars.sh)" && ssh -o StrictHostKeyChecking=accept-new -N -L 3000:127.0.0.1:3000 -p "$$SSH_PORT" -i "$$SSH_KEY_PATH" "$$SSH_USER@$$SSH_HOST"

ansible-tunnel-mailhog:
	eval "$$(cd ansible && ./resolve-ssh-vars.sh)" && ssh -o StrictHostKeyChecking=accept-new -N -L 8025:127.0.0.1:8025 -p "$$SSH_PORT" -i "$$SSH_KEY_PATH" "$$SSH_USER@$$SSH_HOST"

ansible-tunnel-all:
	eval "$$(cd ansible && ./resolve-ssh-vars.sh)" && ssh -o StrictHostKeyChecking=accept-new -N -L 3000:127.0.0.1:3000 -L 8025:127.0.0.1:8025 -p "$$SSH_PORT" -i "$$SSH_KEY_PATH" "$$SSH_USER@$$SSH_HOST"

ansible-tunnel-kill-grafana:
	pkill -f 'ssh .*3000:127.0.0.1:3000' || true

ansible-tunnel-kill-mailhog:
	pkill -f 'ssh .*8025:127.0.0.1:8025' || true

ansible-tunnel-kill-all:
	pkill -f 'ssh .*3000:127.0.0.1:3000|ssh .*8025:127.0.0.1:8025' || true
