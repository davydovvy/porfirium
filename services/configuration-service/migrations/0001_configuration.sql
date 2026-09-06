CREATE TABLE IF NOT EXISTS configuration_revisions (
    revision_id uuid PRIMARY KEY, owner_id uuid NOT NULL, release_id uuid NOT NULL,
    scope text NOT NULL CHECK (scope IN ('user', 'conversation')), conversation_id uuid,
    schema_digest text NOT NULL CHECK (schema_digest ~ '^[0-9a-f]{64}$'),
    values jsonb NOT NULL, secret_references jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((scope = 'conversation') = (conversation_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS configuration_revisions_owner_idx
    ON configuration_revisions(owner_id, release_id, created_at);
CREATE TABLE IF NOT EXISTS configuration_idempotency (
    owner_id uuid NOT NULL, idempotency_key text NOT NULL,
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    revision_id uuid NOT NULL REFERENCES configuration_revisions(revision_id),
    created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(owner_id, idempotency_key)
);
CREATE OR REPLACE FUNCTION reject_configuration_revision_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'configuration revisions are immutable'; END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS configuration_revisions_immutable ON configuration_revisions;
CREATE TRIGGER configuration_revisions_immutable BEFORE UPDATE OR DELETE ON configuration_revisions
FOR EACH ROW EXECUTE FUNCTION reject_configuration_revision_mutation();
