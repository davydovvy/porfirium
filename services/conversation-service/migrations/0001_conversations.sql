CREATE TABLE conversations (
    conversation_id uuid PRIMARY KEY, owner_id uuid NOT NULL, thread_id uuid NOT NULL UNIQUE,
    release_id uuid NOT NULL, configuration_revision_id uuid, title text NOT NULL,
    last_sequence bigint NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (length(title) BETWEEN 1 AND 200)
);
CREATE INDEX conversations_owner_idx ON conversations(owner_id, updated_at DESC);

CREATE TABLE messages (
    message_id uuid PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES conversations,
    run_id uuid NOT NULL, role text NOT NULL CHECK (role IN ('user','assistant','progress','ui')),
    status text NOT NULL CHECK (status IN ('streaming','completed','interrupted','failed')),
    content text NOT NULL DEFAULT '', finish_reason text, usage jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz
);
CREATE INDEX messages_conversation_idx ON messages(conversation_id, created_at, message_id);
CREATE TABLE message_chunks (
    message_id uuid NOT NULL REFERENCES messages, chunk_sequence integer NOT NULL CHECK (chunk_sequence > 0),
    content text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(message_id, chunk_sequence)
);

CREATE TABLE input_requests (
    input_request_id uuid PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES conversations,
    run_id uuid NOT NULL, suspension_id uuid NOT NULL UNIQUE, checkpoint_id uuid NOT NULL,
    prompt text NOT NULL, schema jsonb NOT NULL, state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending','answered','expired','cancelled')),
    response jsonb, response_run_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz
);
CREATE INDEX input_requests_conversation_idx ON input_requests(conversation_id, created_at);

CREATE TABLE presentation_events (
    conversation_id uuid NOT NULL REFERENCES conversations, sequence bigint NOT NULL,
    event_type text NOT NULL, data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(conversation_id, sequence)
);
CREATE TABLE request_idempotency (
    owner_id uuid NOT NULL, operation text NOT NULL, idempotency_key text NOT NULL,
    request_sha256 text NOT NULL, resource_id uuid NOT NULL, conversation_sequence bigint,
    PRIMARY KEY(owner_id, operation, idempotency_key)
);
CREATE TABLE inbox_events (
    event_id uuid PRIMARY KEY, event_type text NOT NULL, processed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE outbox_events (
    event_id uuid PRIMARY KEY, subject text NOT NULL, payload jsonb NOT NULL,
    available_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz, publish_attempts integer NOT NULL DEFAULT 0
);
CREATE INDEX conversation_outbox_pending_idx ON outbox_events(available_at, created_at)
    WHERE published_at IS NULL;
