ALTER TABLE runs ADD COLUMN IF NOT EXISTS run_input jsonb;

ALTER TABLE runs ADD CONSTRAINT runs_run_input_size
    CHECK (run_input IS NULL OR octet_length(run_input::text) <= 24576);
