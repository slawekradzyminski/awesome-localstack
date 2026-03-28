#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_PASS_FILE="${SCRIPT_DIR}/.vault_pass"
INVENTORY_HOST="${1:-awesome_server}"

if [[ ! -f "${VAULT_PASS_FILE}" ]]; then
  echo "Vault password file not found at ${VAULT_PASS_FILE}" >&2
  exit 1
fi

resolve_var() {
  local var_name="$1"

  ansible "${INVENTORY_HOST}" -m debug -a "var=${var_name}" \
    --vault-password-file "${VAULT_PASS_FILE}" \
    |
    sed -nE "s/.*\"${var_name}\": \"(.*)\".*/\\1/p"
}

ssh_host="$(resolve_var ansible_host)"
ssh_port="$(resolve_var ansible_port)"
ssh_user="$(resolve_var ansible_user)"
ssh_key_path="$(resolve_var ansible_ssh_private_key_file)"

if [[ -z "${ssh_host}" || -z "${ssh_port}" || -z "${ssh_user}" || -z "${ssh_key_path}" ]]; then
  echo "Failed to resolve SSH connection details from Ansible inventory" >&2
  exit 1
fi

printf 'SSH_HOST=%q\n' "${ssh_host}"
printf 'SSH_PORT=%q\n' "${ssh_port}"
printf 'SSH_USER=%q\n' "${ssh_user}"
printf 'SSH_KEY_PATH=%q\n' "${ssh_key_path}"
