ALTER TABLE result_proposals ADD COLUMN traceparent text;
ALTER TABLE result_proposals ADD COLUMN correlation_id uuid;
ALTER TABLE result_proposals ADD COLUMN causation_id uuid;

UPDATE result_proposals SET
    correlation_id = event_id,
    causation_id = event_id,
    traceparent = '00-' || replace(event_id::text, '-', '') || '-' ||
        substring(replace(event_id::text, '-', '') from 1 for 16) || '-00';

ALTER TABLE result_proposals ALTER COLUMN traceparent SET NOT NULL;
ALTER TABLE result_proposals ALTER COLUMN correlation_id SET NOT NULL;
ALTER TABLE result_proposals ALTER COLUMN causation_id SET NOT NULL;

ALTER TABLE result_proposals ADD CONSTRAINT result_proposals_traceparent_format
    CHECK (traceparent ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$');
