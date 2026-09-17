-- Short, unguessable code for the receipt link sent by SMS (SMS is billed
-- per 160-char segment, so the full reference — which embeds the student ID —
-- is too long to link directly without spilling into a second segment).
ALTER TABLE dues.payments ADD COLUMN IF NOT EXISTS short_code VARCHAR(12);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dues_payments_short_code
    ON dues.payments (short_code) WHERE short_code IS NOT NULL;

-- Every webhook delivery, verified or not, so a future admin page can show
-- full payment history without anything having to be re-instrumented.
CREATE TABLE IF NOT EXISTS dues.webhook_events (
    id          SERIAL PRIMARY KEY,
    event       VARCHAR(40),
    reference   VARCHAR(80),
    verified    BOOLEAN NOT NULL,
    raw_body    TEXT NOT NULL,
    received_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_dues_webhook_events_reference ON dues.webhook_events (reference);
