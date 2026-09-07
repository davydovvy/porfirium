CREATE TABLE IF NOT EXISTS tool_invocations (
    run_id uuid NOT NULL,
    invocation_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    lease_epoch bigint NOT NULL CHECK (lease_epoch > 0),
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    state text NOT NULL CHECK (state IN ('executing', 'completed')),
    result jsonb,
    is_error boolean,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    PRIMARY KEY (run_id, invocation_id),
    CHECK (
        (state = 'executing' AND result IS NULL AND is_error IS NULL AND completed_at IS NULL)
        OR (state = 'completed' AND result IS NOT NULL AND is_error IS NOT NULL
            AND completed_at IS NOT NULL)
    )
);
