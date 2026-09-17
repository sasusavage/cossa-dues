-- Everything COSSA-dues-specific lives in its own schema. The `users` table
-- referenced below belongs to the existing voting system that shares this
-- database — it is only ever read here, never altered, and matched_user_id
-- deliberately has no foreign key onto it so a row deleted by that system can
-- never be blocked by anything in this one.

CREATE SCHEMA IF NOT EXISTS dues;

-- Result of a /check lookup, kept server-side so the amount and category
-- can never be edited by the client between the confirm screen and /pay.
CREATE TABLE IF NOT EXISTS dues.pending_checks (
    token           VARCHAR(64) PRIMARY KEY,
    full_name       VARCHAR(300) NOT NULL,
    student_id      VARCHAR(30)  NOT NULL,
    phone_number    VARCHAR(20)  NOT NULL,
    email           VARCHAR(200),
    match_type      VARCHAR(24)  NOT NULL,
    matched_user_id INTEGER,
    department      VARCHAR(200),
    program         VARCHAR(200),
    amount          NUMERIC(10,2) NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dues.payments (
    id                SERIAL PRIMARY KEY,
    reference         VARCHAR(80) UNIQUE NOT NULL,
    full_name         VARCHAR(300) NOT NULL,
    student_id        VARCHAR(30)  NOT NULL,
    matched_user_id   INTEGER,
    match_type        VARCHAR(24)  NOT NULL,
    department        VARCHAR(200),
    program           VARCHAR(200),
    phone_number      VARCHAR(20)  NOT NULL,
    email             VARCHAR(200),
    amount            NUMERIC(10,2) NOT NULL,
    currency          VARCHAR(8)   NOT NULL DEFAULT 'GHS',
    status            VARCHAR(20)  NOT NULL DEFAULT 'pending',
    checkout_url      TEXT,
    payer_phone       VARCHAR(20),
    payer_name        VARCHAR(200),
    paid_at           TIMESTAMP,
    sms_sent          BOOLEAN NOT NULL DEFAULT FALSE,
    telegram_notified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMP NOT NULL DEFAULT now(),
    updated_at        TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_dues_payments_student_id ON dues.payments (student_id);
CREATE INDEX IF NOT EXISTS ix_dues_payments_matched_user_id ON dues.payments (matched_user_id);
CREATE INDEX IF NOT EXISTS ix_dues_payments_status ON dues.payments (status);

CREATE TABLE IF NOT EXISTS dues.issue_reports (
    id           SERIAL PRIMARY KEY,
    full_name    VARCHAR(300) NOT NULL,
    student_id   VARCHAR(30)  NOT NULL,
    phone_number VARCHAR(20)  NOT NULL,
    email        VARCHAR(200),
    category     VARCHAR(24)  NOT NULL,
    reason       TEXT NOT NULL,
    status       VARCHAR(20)  NOT NULL DEFAULT 'open',
    created_at   TIMESTAMP NOT NULL DEFAULT now()
);
