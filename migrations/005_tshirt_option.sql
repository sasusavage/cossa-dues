-- Continuing students can add a COSSA t-shirt to their dues payment. Stored
-- on both tables: pending_checks so /pay knows what was chosen on the confirm
-- screen, payments so the record (and the Telegram alert) shows who ordered one.
ALTER TABLE dues.pending_checks ADD COLUMN IF NOT EXISTS tshirt BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE dues.payments ADD COLUMN IF NOT EXISTS tshirt BOOLEAN NOT NULL DEFAULT FALSE;
