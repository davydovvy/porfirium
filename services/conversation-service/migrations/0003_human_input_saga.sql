ALTER TABLE input_requests DROP CONSTRAINT input_requests_state_check;
ALTER TABLE input_requests ALTER COLUMN state SET DEFAULT 'reserved';
ALTER TABLE input_requests ADD CONSTRAINT input_requests_state_check
    CHECK (state IN ('reserved','pending','answered','expired','cancelled'));
ALTER TABLE input_requests ADD COLUMN delegation_grant_id uuid;
ALTER TABLE conversations ADD COLUMN delegation_grant_id uuid;

CREATE TABLE suspension_commitments (
    suspension_id uuid PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE,
    run_id uuid NOT NULL,
    checkpoint_id uuid NOT NULL,
    input_request_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
