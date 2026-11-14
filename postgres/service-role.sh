#!/usr/bin/env bash
# Gives one service its own PostgreSQL role, limited to a schema of the same
# backend database (warehouse-service: role and schema `warehouse`;
# payment-service: role and schema `payment`; notification-service: role and
# schema `notification`). Idempotent: it runs before every
# service start, on fresh and on existing databases (where it takes over the
# schema and the tables an earlier deployment created as the superuser). The
# backend's tables in `public` stay owned by the superuser without grants, so
# the role cannot read or change them, and a schema created with AUTHORIZATION
# grants nothing to other roles, so the services cannot read each other's data.
#
# Environment: PGHOST, PGDATABASE, PGUSER and PGPASSWORD (superuser connection),
# SERVICE_ROLE (role name), SERVICE_SCHEMA (schema name, defaults to the role)
# and SERVICE_DB_PASSWORD (password for the role).
set -euo pipefail

: "${PGHOST:?}" "${PGDATABASE:?}" "${PGUSER:?}" "${SERVICE_ROLE:?}" "${SERVICE_DB_PASSWORD:?}"
SERVICE_SCHEMA="${SERVICE_SCHEMA:-$SERVICE_ROLE}"

identifier='^[a-z_][a-z0-9_]{0,62}$'
if [[ ! "$SERVICE_ROLE" =~ $identifier || ! "$SERVICE_SCHEMA" =~ $identifier ]]; then
  echo "SERVICE_ROLE and SERVICE_SCHEMA must be lower-case SQL identifiers" >&2
  exit 1
fi
if [[ "$SERVICE_SCHEMA" == public || "$SERVICE_SCHEMA" == pg_* || "$SERVICE_SCHEMA" == information_schema ]]; then
  echo "SERVICE_SCHEMA must not be a system or the backend's public schema" >&2
  exit 1
fi

for _ in $(seq 1 60); do
  pg_isready -q && break
  sleep 1
done

psql -v ON_ERROR_STOP=1 \
  -v role="$SERVICE_ROLE" \
  -v schema="$SERVICE_SCHEMA" \
  -v role_password="$SERVICE_DB_PASSWORD" \
  -v database="$PGDATABASE" <<'SQL'
SELECT NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'role') AS create_role \gset
\if :create_role
CREATE ROLE :"role" LOGIN;
\endif
ALTER ROLE :"role" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'role_password';
GRANT CONNECT ON DATABASE :"database" TO :"role";

CREATE SCHEMA IF NOT EXISTS :"schema" AUTHORIZATION :"role";
ALTER SCHEMA :"schema" OWNER TO :"role";

-- Tables created by an earlier deployment as the superuser, including Flyway's
-- history table. Identity sequences and indexes follow their table.
SELECT set_config('service_role.role', :'role', false) AS _role_setting,
       set_config('service_role.schema', :'schema', false) AS _schema_setting \gset
DO $$
DECLARE
    service_role text := current_setting('service_role.role');
    service_schema text := current_setting('service_role.schema');
    item record;
BEGIN
    FOR item IN
        SELECT c.relname, c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = service_schema
          AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
          AND pg_get_userbyid(c.relowner) <> service_role
          AND NOT (c.relkind = 'S' AND EXISTS (
              SELECT FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('a', 'i')))
    LOOP
        EXECUTE format('ALTER %s %I.%I OWNER TO %I',
            CASE item.relkind
                WHEN 'S' THEN 'SEQUENCE'
                WHEN 'v' THEN 'VIEW'
                WHEN 'm' THEN 'MATERIALIZED VIEW'
                ELSE 'TABLE'
            END,
            service_schema, item.relname, service_role);
    END LOOP;
END
$$;

REVOKE CREATE ON SCHEMA public FROM :"role";
SQL

if [[ "$(psql -tA -v role="$SERVICE_ROLE" <<'SQL'
SELECT has_schema_privilege(:'role', 'public', 'CREATE')
       OR EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                  WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
                    AND has_table_privilege(:'role', c.oid, 'SELECT'));
SQL
)" != "f" ]]; then
  echo "$SERVICE_ROLE role can still read or create objects in schema public" >&2
  exit 1
fi
echo "$SERVICE_ROLE role ready: owns schema $SERVICE_SCHEMA, no access to schema public"
