-- Independent manual inputs only; existing profile, activity and model rows stay intact.
CREATE TABLE user_training_context (
    user_id text PRIMARY KEY,
    block_priority text CHECK (block_priority IN ('long_z2', 'z2', 'intensity', 'recovery')),
    revision bigint NOT NULL CHECK (revision > 0)
);

-- Atomic bounded weekly document, validated against WeekPlan on every app read/write.
-- No copies of Strava activities, load, readiness or feedback are stored here.
CREATE TABLE training_week_plan (
    user_id text NOT NULL REFERENCES user_training_context(user_id),
    week_start date NOT NULL CHECK (extract(isodow from week_start) = 1),
    plan jsonb NOT NULL CHECK (jsonb_typeof(plan) = 'object'),
    PRIMARY KEY (user_id, week_start)
);
