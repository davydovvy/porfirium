CREATE TABLE result_proposals (
    run_id uuid PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE,
    conversation_id uuid NOT NULL REFERENCES conversations,
    final_message_ids uuid[] NOT NULL,
    confirmation_event_id uuid,
    created_at timestamptz NOT NULL DEFAULT now()
);
