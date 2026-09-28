-- Simple expense ledger so cash going out (e.g. supplies bought for COSSA)
-- shows up in the same audit as dues collected, without needing a separate
-- system. No admin UI yet — rows are inserted directly for now.
CREATE TABLE IF NOT EXISTS dues.expenses (
    id          SERIAL PRIMARY KEY,
    amount      NUMERIC(10,2) NOT NULL,
    paid_to     VARCHAR(200) NOT NULL,
    reason      TEXT NOT NULL,
    spent_at    TIMESTAMP NOT NULL,
    recorded_at TIMESTAMP NOT NULL DEFAULT now()
);
