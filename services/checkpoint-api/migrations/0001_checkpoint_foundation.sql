CREATE TABLE checkpoint_leases (
    run_id uuid PRIMARY KEY,
    attempt_id uuid NOT NULL,
    lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE checkpoints (
    checkpoint_id uuid PRIMARY KEY,
    thread_id uuid NOT NULL,
    run_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
    version bigint NOT NULL CHECK (version > 0),
    serialization_version varchar(32) NOT NULL,
    payload bytea NOT NULL CHECK (octet_length(payload) <= 1048576),
    payload_sha256 char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(thread_id, version)
);
CREATE INDEX checkpoints_thread_created_idx ON checkpoints(thread_id, created_at DESC);

CREATE TABLE checkpoint_idempotency (
    run_id uuid NOT NULL,
    idempotency_key varchar(128) NOT NULL,
    request_hash text NOT NULL,
    checkpoint_id uuid NOT NULL REFERENCES checkpoints(checkpoint_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(run_id, idempotency_key)
);
