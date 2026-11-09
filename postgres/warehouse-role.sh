#!/usr/bin/env bash
# Gives warehouse-service its own PostgreSQL role, limited to the `warehouse`
# schema of the backend database. Idempotent: it runs before every
# warehouse-service start, on fresh and on existing databases (where it takes
# over the schema and the tables an earlier deployment created as the
# superuser). The backend's tables in `public` stay owned by the superuser
# without grants, so the warehouse role cannot read or change them.
#
# Environment: PGHOST, PGDATABASE, PGUSER and PGPASSWORD (superuser connection)
# and WAREHOUSE_DB_PASSWORD (password for the `warehouse` role).
set -euo pipefail

: "${PGHOST:?}" "${PGDATABASE:?}" "${PGUSER:?}" "${WAREHOUSE_DB_PASSWORD:?}"

for _ in $(seq 1 60); do
  pg_isready -q && break
  sleep 1
done

psql -v ON_ERROR_STOP=1 -v warehouse_password="$WAREHOUSE_DB_PASSWORD" -v database="$PGDATABASE" <<'SQL'
SELECT NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'warehouse') AS create_role \gset
\if :create_role
CREATE ROLE warehouse LOGIN;
\endif
ALTER ROLE warehouse WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'warehouse_password';
GRANT CONNECT ON DATABASE :"database" TO warehouse;

CREATE SCHEMA IF NOT EXISTS warehouse AUTHORIZATION warehouse;
ALTER SCHEMA warehouse OWNER TO warehouse;

-- Tables created by an earlier deployment as the superuser, including Flyway's
-- history table. Identity sequences and indexes follow their table.
DO $$
DECLARE
    item record;
BEGIN
    FOR item IN
        SELECT c.relname, c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'warehouse'
          AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
          AND pg_get_userbyid(c.relowner) <> 'warehouse'
          AND NOT (c.relkind = 'S' AND EXISTS (
              SELECT FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('a', 'i')))
    LOOP
        EXECUTE format('ALTER %s warehouse.%I OWNER TO warehouse',
            CASE item.relkind
                WHEN 'S' THEN 'SEQUENCE'
                WHEN 'v' THEN 'VIEW'
                WHEN 'm' THEN 'MATERIALIZED VIEW'
                ELSE 'TABLE'
            END,
            item.relname);
    END LOOP;
END
$$;

REVOKE CREATE ON SCHEMA public FROM warehouse;
SQL

if [[ "$(psql -tAc "SELECT has_schema_privilege('warehouse', 'public', 'CREATE')
                     OR EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                                WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
                                  AND has_table_privilege('warehouse', c.oid, 'SELECT'))")" != "f" ]]; then
  echo "warehouse role can still read or create objects in schema public" >&2
  exit 1
fi
echo "warehouse role ready: owns schema warehouse, no access to schema public"
