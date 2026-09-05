#!/bin/sh
set -eu

create_owner_and_database() {
  owner="$1"
  database="$2"
  password="$3"

  psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    --set=owner="$owner" --set=password="$password" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'owner', :'password')
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = :'owner') \gexec
SQL
  psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    --set=owner="$owner" --set=database="$database" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'database', :'owner')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'database') \gexec
SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', :'database') \gexec
SQL
}

create_owner_and_database conversation_service conversation "$CONVERSATION_DB_PASSWORD"
create_owner_and_database agent_registry registry "$REGISTRY_DB_PASSWORD"
create_owner_and_database agent_runner runner "$RUNNER_DB_PASSWORD"
create_owner_and_database agent_runtime runtime "$RUNTIME_DB_PASSWORD"
create_owner_and_database identity_delegation delegation "$DELEGATION_DB_PASSWORD"
create_owner_and_database configuration_service configuration "$CONFIGURATION_DB_PASSWORD"
create_owner_and_database checkpoint_api checkpoint "$CHECKPOINT_DB_PASSWORD"
