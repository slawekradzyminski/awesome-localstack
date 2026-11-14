#!/usr/bin/env bash
# Entry point of the one-shot postgres-roles services: prepares the database
# role and schema of every service that shares the backend database
# (postgres/service-role.sh). Runs before every warehouse-service,
# payment-service and notification-service start.
#
# Environment: PGHOST, PGDATABASE, PGUSER and PGPASSWORD (superuser connection),
# WAREHOUSE_DB_PASSWORD, PAYMENT_DB_PASSWORD and NOTIFICATION_DB_PASSWORD (role
# passwords).
set -euo pipefail

: "${WAREHOUSE_DB_PASSWORD:?}" "${PAYMENT_DB_PASSWORD:?}" "${NOTIFICATION_DB_PASSWORD:?}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVICE_ROLE=warehouse SERVICE_SCHEMA=warehouse SERVICE_DB_PASSWORD="$WAREHOUSE_DB_PASSWORD" \
  bash "$script_dir/service-role.sh"
SERVICE_ROLE=payment SERVICE_SCHEMA=payment SERVICE_DB_PASSWORD="$PAYMENT_DB_PASSWORD" \
  bash "$script_dir/service-role.sh"
SERVICE_ROLE=notification SERVICE_SCHEMA=notification SERVICE_DB_PASSWORD="$NOTIFICATION_DB_PASSWORD" \
  bash "$script_dir/service-role.sh"
