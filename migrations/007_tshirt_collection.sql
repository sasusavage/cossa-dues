-- Every fresher's GHS 100 already includes a t-shirt (that's the whole
-- difference from the GHS 50 continuing fee), so they're eligible the
-- moment they pay — no separate add-on step for them like continuing
-- students have. Backfill existing paid freshers so `tshirt` consistently
-- means "eligible for a shirt" across both categories.
UPDATE dues.payments SET tshirt = true WHERE status = 'successful' AND match_type = 'fresher' AND NOT tshirt;

-- Tracks collection separately from eligibility: whether the shirt has
-- actually been handed to the student, set by whoever hands it out
-- (scripts/mark_tshirt_collected.py — no admin UI yet).
ALTER TABLE dues.payments ADD COLUMN IF NOT EXISTS shirt_collected BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE dues.payments ADD COLUMN IF NOT EXISTS shirt_collected_at TIMESTAMP;
