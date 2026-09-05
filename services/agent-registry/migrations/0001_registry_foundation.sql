CREATE TABLE agents (
    agent_id text PRIMARY KEY
        CHECK (agent_id ~ '^[a-z][a-z0-9-]{0,62}$'),
    name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 100),
    description text NOT NULL CHECK (char_length(description) <= 500),
    default_release_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE releases (
    release_id uuid PRIMARY KEY,
    agent_id text NOT NULL REFERENCES agents(agent_id),
    version text NOT NULL
        CHECK (version ~ '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'),
    image text NOT NULL CHECK (image ~ '^[^@[:space:]]+@sha256:[0-9a-f]{64}$'),
    image_digest text NOT NULL CHECK (image_digest ~ '^sha256:[0-9a-f]{64}$'),
    manifest jsonb NOT NULL,
    manifest_sha256 text NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    provenance jsonb NOT NULL,
    sdk_constraint text NOT NULL,
    status text NOT NULL DEFAULT 'published'
        CHECK (status IN ('published', 'deprecated')),
    published_by text NOT NULL,
    published_at timestamptz NOT NULL DEFAULT now(),
    deprecated_by text,
    deprecated_at timestamptz,
    CHECK (
        (status = 'published' AND deprecated_by IS NULL AND deprecated_at IS NULL)
        OR (status = 'deprecated' AND deprecated_by IS NOT NULL AND deprecated_at IS NOT NULL)
    ),
    UNIQUE (agent_id, version),
    UNIQUE (image)
);

ALTER TABLE agents
    ADD CONSTRAINT agents_default_release_fk
    FOREIGN KEY (default_release_id) REFERENCES releases(release_id);

CREATE TABLE access_grants (
    grant_id uuid PRIMARY KEY,
    agent_id text NOT NULL REFERENCES agents(agent_id),
    subject_type text NOT NULL CHECK (subject_type IN ('user', 'group', 'role')),
    subject_id text NOT NULL CHECK (char_length(subject_id) BETWEEN 1 AND 255),
    permission text NOT NULL CHECK (permission IN ('discover', 'run', 'publish', 'admin')),
    granted_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    UNIQUE NULLS NOT DISTINCT (agent_id, subject_type, subject_id, permission, revoked_at)
);

CREATE INDEX access_grants_active_subject_idx
    ON access_grants (subject_type, subject_id, agent_id)
    WHERE revoked_at IS NULL;

CREATE TABLE access_grant_audit (
    audit_id uuid PRIMARY KEY,
    grant_id uuid NOT NULL REFERENCES access_grants(grant_id),
    action text NOT NULL CHECK (action IN ('granted', 'revoked')),
    actor_id text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE publication_audit (
    audit_id uuid PRIMARY KEY,
    release_id uuid NOT NULL REFERENCES releases(release_id),
    action text NOT NULL
        CHECK (action IN ('published', 'deprecated', 'default_release_changed')),
    actor_id text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE run_specifications (
    specification_id uuid PRIMARY KEY,
    run_id uuid NOT NULL UNIQUE,
    release_id uuid NOT NULL REFERENCES releases(release_id),
    user_id uuid NOT NULL,
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    signature bytea NOT NULL CHECK (octet_length(signature) = 64),
    key_id text NOT NULL CHECK (char_length(key_id) BETWEEN 1 AND 128),
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > issued_at),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE idempotency_records (
    actor_id text NOT NULL,
    operation text NOT NULL,
    idempotency_key text NOT NULL
        CHECK (char_length(idempotency_key) BETWEEN 8 AND 128),
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    response_status integer NOT NULL CHECK (response_status BETWEEN 200 AND 599),
    result_release_id uuid REFERENCES releases(release_id),
    result_grant_id uuid REFERENCES access_grants(grant_id),
    result_specification_id uuid REFERENCES run_specifications(specification_id),
    response_body jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (actor_id, operation, idempotency_key)
);

CREATE FUNCTION reject_release_content_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(
        NEW.release_id, NEW.agent_id, NEW.version, NEW.image, NEW.image_digest,
        NEW.manifest, NEW.manifest_sha256, NEW.provenance, NEW.sdk_constraint,
        NEW.published_by, NEW.published_at
    ) IS DISTINCT FROM ROW(
        OLD.release_id, OLD.agent_id, OLD.version, OLD.image, OLD.image_digest,
        OLD.manifest, OLD.manifest_sha256, OLD.provenance, OLD.sdk_constraint,
        OLD.published_by, OLD.published_at
    ) THEN
        RAISE EXCEPTION 'immutable release content cannot be changed';
    END IF;
    IF OLD.status = 'deprecated' AND NEW.status <> 'deprecated' THEN
        RAISE EXCEPTION 'a deprecated release cannot be republished';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER releases_immutable_content
BEFORE UPDATE ON releases
FOR EACH ROW EXECUTE FUNCTION reject_release_content_change();

CREATE FUNCTION reject_audit_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'publication audit is append-only';
END;
$$;

CREATE TRIGGER publication_audit_append_only
BEFORE UPDATE OR DELETE ON publication_audit
FOR EACH ROW EXECUTE FUNCTION reject_audit_change();

CREATE TRIGGER access_grant_audit_append_only
BEFORE UPDATE OR DELETE ON access_grant_audit
FOR EACH ROW EXECUTE FUNCTION reject_audit_change();

CREATE TRIGGER run_specifications_immutable
BEFORE UPDATE OR DELETE ON run_specifications
FOR EACH ROW EXECUTE FUNCTION reject_audit_change();
