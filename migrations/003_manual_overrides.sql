-- For continuing students the automatic check can't find in the shared
-- `users` table (wrong/missing entry there, never registered for voting,
-- etc). An admin vouches for them here instead of anyone touching that
-- table. Keyed on student_id; the submitted name still has to contain
-- every word of the name recorded here before it counts as a match.
CREATE TABLE IF NOT EXISTS dues.manual_overrides (
    id         SERIAL PRIMARY KEY,
    student_id VARCHAR(30) NOT NULL,
    full_name  VARCHAR(300) NOT NULL,
    note       TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dues_manual_overrides_student_id
    ON dues.manual_overrides (UPPER(student_id));
