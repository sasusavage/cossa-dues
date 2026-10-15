-- Distinguishes a payment taken through SasuSync from one an exec collected
-- in person (cash/MoMo handed over directly) and logged by hand.
ALTER TABLE dues.payments ADD COLUMN IF NOT EXISTS channel VARCHAR(20) NOT NULL DEFAULT 'online';
