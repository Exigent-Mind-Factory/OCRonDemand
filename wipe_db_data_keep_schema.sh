#!/usr/bin/env bash
set -euo pipefail

# ---- Config (override via env vars if you want) ----
PG_CONTAINER="${PG_CONTAINER:-ocrondemand-postgres-1}"
PG_USER="${PG_USER:-Admin}"
PG_DB="${PG_DB:-OCRonDemandDB}"

echo "==> Truncating all tables in non-system schemas"
echo "    Container: ${PG_CONTAINER}"
echo "    DB:        ${PG_DB}"
echo "    User:      ${PG_USER}"
echo

docker exec -i "${PG_CONTAINER}" psql -U "${PG_USER}" -d "${PG_DB}" -v ON_ERROR_STOP=1 <<'SQL'
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT schemaname, tablename
    FROM pg_tables
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  LOOP
    EXECUTE format(
      'TRUNCATE TABLE %I.%I RESTART IDENTITY CASCADE',
      r.schemaname, r.tablename
    );
  END LOOP;
END $$;
SQL

echo
echo "==> Done. Remaining tables (schemas intact):"

docker exec -i "${PG_CONTAINER}" psql -U "${PG_USER}" -d "${PG_DB}" -v ON_ERROR_STOP=1 <<'SQL'
SELECT schemaname, tablename
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schemaname, tablename;
SQL

