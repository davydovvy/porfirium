CREATE TABLE IF NOT EXISTS runtime_attempts (
    run_id uuid PRIMARY KEY,
    attempt_id uuid NOT NULL,
    lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
    user_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    thread_id uuid NOT NULL,
    deadline timestamptz NOT NULL,
    last_sequence bigint NOT NULL DEFAULT 0,
    last_heartbeat_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS accepted_frames (
    run_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    lease_epoch bigint NOT NULL,
    sequence bigint NOT NULL,
    idempotency_key text NOT NULL,
    payload_type text NOT NULL,
    durable_event_id uuid,
    accepted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, attempt_id, lease_epoch, sequence),
    UNIQUE (run_id, attempt_id, lease_epoch, idempotency_key)
);

CREATE TABLE IF NOT EXISTS outbox_events (
    event_id uuid PRIMARY KEY,
    subject text NOT NULL,
    payload jsonb NOT NULL,
    available_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    publish_attempts integer NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0)
);

CREATE INDEX IF NOT EXISTS runtime_outbox_pending_idx
    ON outbox_events (available_at, created_at) WHERE published_at IS NULL;
