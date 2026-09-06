CREATE TABLE run_completion (
    run_id uuid PRIMARY KEY REFERENCES runs(run_id),
    proposal_event_id uuid NOT NULL UNIQUE,
    attempt_id uuid NOT NULL REFERENCES attempts(attempt_id),
    lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
    final_message_ids uuid[] NOT NULL DEFAULT '{}',
    final_checkpoint_id uuid,
    required_confirmations text[] NOT NULL,
    messages_confirmed boolean NOT NULL DEFAULT false,
    checkpoint_confirmed boolean NOT NULL DEFAULT false,
    proposed_at timestamptz NOT NULL DEFAULT now(),
    reconciled_at timestamptz
);

CREATE TABLE run_event_inbox (
    event_id uuid PRIMARY KEY,
    event_type text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE run_confirmations (
    run_id uuid NOT NULL REFERENCES runs(run_id),
    confirmation text NOT NULL CHECK (confirmation IN ('messages', 'checkpoint')),
    payload jsonb NOT NULL,
    PRIMARY KEY (run_id, confirmation)
);

ALTER TABLE attempts ADD COLUMN visible_output boolean NOT NULL DEFAULT false;
ALTER TABLE attempts ADD COLUMN active_message_id uuid;
