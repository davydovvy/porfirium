CREATE TABLE IF NOT EXISTS delegation_grants (
    grant_id uuid PRIMARY KEY, user_id uuid NOT NULL, conversation_id uuid NOT NULL,
    release_id uuid NOT NULL, maximum_scopes text[] NOT NULL,
    expires_at timestamptz NOT NULL, revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS delegation_grants_user_idx ON delegation_grants(user_id, expires_at);
CREATE TABLE IF NOT EXISTS delegation_idempotency (
    actor_id uuid NOT NULL, operation text NOT NULL, idempotency_key text NOT NULL,
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    grant_id uuid NOT NULL REFERENCES delegation_grants(grant_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(actor_id, operation, idempotency_key)
);
