CREATE TABLE runner_dead_letters (
    dead_letter_id uuid PRIMARY KEY,
    original_event_id uuid NOT NULL,
    original_subject text NOT NULL CHECK (length(original_subject) BETWEEN 1 AND 256),
    original_type text NOT NULL CHECK (length(original_type) BETWEEN 1 AND 128),
    consumer text NOT NULL CHECK (length(consumer) BETWEEN 1 AND 128),
    attempts integer NOT NULL CHECK (attempts > 0),
    error_code text NOT NULL CHECK (length(error_code) BETWEEN 1 AND 64),
    original_payload_ciphertext bytea NOT NULL,
    first_failed_at timestamptz NOT NULL,
    last_failed_at timestamptz NOT NULL,
    replayed_at timestamptz,
    replayed_by text,
    UNIQUE (original_event_id, consumer)
);

CREATE TABLE runner_operator_audit (
    audit_id uuid PRIMARY KEY,
    action text NOT NULL,
    subject_id uuid NOT NULL,
    operator_id text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX runner_dead_letters_pending_idx
    ON runner_dead_letters (last_failed_at, dead_letter_id)
    WHERE replayed_at IS NULL;
