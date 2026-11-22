-- Our own COSSA-scoped roster: CS and IT students on the Accra campus only.
-- Seeded from the shared `users` table (never written to directly — see
-- 001_dues_schema.sql) and kept up to date from faculty student registers.
-- This table belongs entirely to this app; nothing in `users` is touched.
CREATE TABLE IF NOT EXISTS dues.student_roster (
    student_id  VARCHAR(30) PRIMARY KEY,
    full_name   VARCHAR(300) NOT NULL,
    department  VARCHAR(10)  NOT NULL,  -- 'CS' or 'IT'
    phone_number VARCHAR(20),
    source      VARCHAR(30)  NOT NULL DEFAULT 'users_table',
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP NOT NULL DEFAULT now()
);
