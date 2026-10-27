#!/bin/sh
# Runs once, when the database volume is first created: gives Umami its own
# role and database inside Manara's PostgreSQL, so its data stays apart from
# the app's tables (and from rahmahealth.net's Umami entirely).
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v umami_password="$UMAMI_DB_PASSWORD" <<'SQL'
CREATE ROLE umami LOGIN PASSWORD :'umami_password';
CREATE DATABASE umami OWNER umami;
REVOKE ALL ON DATABASE umami FROM PUBLIC;
REVOKE ALL ON DATABASE manara FROM PUBLIC;
SQL
