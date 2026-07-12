ALTER TABLE kc_schedules
    DROP COLUMN IF EXISTS temporal_schedule_id;

ALTER TABLE kc_schedule_runs
    ADD COLUMN IF NOT EXISTS delivery_id VARCHAR(512);

CREATE UNIQUE INDEX IF NOT EXISTS uq_kc_schedule_runs_delivery_id
    ON kc_schedule_runs (delivery_id)
    WHERE delivery_id IS NOT NULL;
