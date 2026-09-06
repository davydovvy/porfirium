CREATE TYPE run_state AS ENUM (
    'requested', 'accepted', 'scheduled', 'starting', 'running', 'suspending',
    'waiting_for_input', 'completion_reconciling', 'cancelling', 'completed', 'failed',
    'cancelled'
);

CREATE TYPE attempt_state AS ENUM ('starting', 'running', 'stopping', 'exited', 'failed');

CREATE TABLE runs (
    run_id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    thread_id uuid NOT NULL,
    release_id uuid NOT NULL,
    delegation_grant_id uuid NOT NULL,
    configuration_revision_id uuid,
    starting_checkpoint_id uuid,
    trigger jsonb NOT NULL,
    trace_id text NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    specification jsonb NOT NULL,
    specification_sha256 text NOT NULL CHECK (specification_sha256 ~ '^[0-9a-f]{64}$'),
    state run_state NOT NULL DEFAULT 'accepted',
    active_attempt_id uuid,
    lease_epoch bigint NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
    terminal_code text CHECK (length(terminal_code) <= 64),
    cancellation_requested_at timestamptz,
    deadline_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE run_idempotency (
    operation text NOT NULL,
    idempotency_key text NOT NULL,
    request_sha256 text NOT NULL,
    run_id uuid NOT NULL REFERENCES runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (operation, idempotency_key)
);

CREATE TABLE attempts (
    attempt_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES runs(run_id),
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
    state attempt_state NOT NULL DEFAULT 'starting',
    container_id text UNIQUE,
    container_name text NOT NULL UNIQUE,
    deadline_at timestamptz NOT NULL,
    started_at timestamptz,
    ended_at timestamptz,
    exit_code integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, attempt_number),
    UNIQUE (run_id, lease_epoch)
);

ALTER TABLE runs ADD CONSTRAINT runs_active_attempt_fk
    FOREIGN KEY (active_attempt_id) REFERENCES attempts(attempt_id);

CREATE UNIQUE INDEX attempts_one_active_per_run_idx ON attempts(run_id)
    WHERE state IN ('starting', 'running', 'stopping');

