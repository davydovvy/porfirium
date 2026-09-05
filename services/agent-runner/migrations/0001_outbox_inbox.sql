CREATE TABLE IF NOT EXISTS outbox_events (
    event_id uuid PRIMARY KEY,
    subject text NOT NULL,
    payload jsonb NOT NULL,
    available_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    publish_attempts integer NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0)
);

CREATE INDEX IF NOT EXISTS outbox_events_pending_idx
    ON outbox_events (available_at, created_at)
    WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS inbox_events (
    event_id uuid NOT NULL,
    handler text NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, handler)
);

-- Phase 6 replaces this minimal gate effect with admitted run and attempt scheduling state while
-- preserving the inbox transaction boundary.
CREATE TABLE IF NOT EXISTS schedule_effects (
    event_id uuid PRIMARY KEY,
    run_id uuid NOT NULL UNIQUE,
    scheduled_at timestamptz NOT NULL DEFAULT now()
);
