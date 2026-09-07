ALTER TABLE attempts ADD COLUMN network_name text;

UPDATE attempts
SET network_name = 'porfirium-attempt-' || attempt_id::text;

ALTER TABLE attempts ALTER COLUMN network_name SET NOT NULL;
ALTER TABLE attempts ADD CONSTRAINT attempts_network_name_unique UNIQUE (network_name);
ALTER TABLE attempts ADD CONSTRAINT attempts_network_name_format CHECK (
    network_name ~ '^porfirium-attempt-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
);
