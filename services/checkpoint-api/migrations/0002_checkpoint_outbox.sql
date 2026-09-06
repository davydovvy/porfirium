CREATE TABLE outbox_events (
    event_id uuid PRIMARY KEY, subject text NOT NULL, payload jsonb NOT NULL,
    available_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz, publish_attempts integer NOT NULL DEFAULT 0
);
CREATE INDEX checkpoint_outbox_pending_idx ON outbox_events(available_at, created_at)
    WHERE published_at IS NULL;
