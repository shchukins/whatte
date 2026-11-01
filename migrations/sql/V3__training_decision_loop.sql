-- Immutable training-policy evidence, separate from readiness/model snapshots.
CREATE TABLE training_decision (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id text NOT NULL REFERENCES user_training_context(user_id),
    decision_day date NOT NULL,
    week_start date NOT NULL,
    target_session_id text NOT NULL,
    context_revision bigint NOT NULL,
    input_json jsonb NOT NULL,
    decision_json jsonb NOT NULL,
    content_fingerprint text NOT NULL,
    proposed_at timestamptz NOT NULL DEFAULT now(),
    presented_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, decision_day, content_fingerprint)
);

-- No answer row means proposed; the original recommendation is never overwritten.
CREATE TABLE training_decision_choice (
    decision_id bigint PRIMARY KEY REFERENCES training_decision(id),
    choice text NOT NULL CHECK (choice IN ('accepted', 'declined')),
    chosen_at timestamptz NOT NULL DEFAULT now(),
    applied_revision bigint NOT NULL
);

-- Explicit correspondence only. A different workout is evidence, not completion.
CREATE TABLE training_session_activity (
    user_id text NOT NULL REFERENCES user_training_context(user_id),
    week_start date NOT NULL,
    session_id text NOT NULL,
    canonical_activity_id bigint NOT NULL,
    decision_id bigint REFERENCES training_decision(id),
    correspondence text NOT NULL CHECK (correspondence IN ('fulfilled', 'different')),
    confirmed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, canonical_activity_id)
);
CREATE UNIQUE INDEX training_session_fulfilled_once
    ON training_session_activity (user_id, week_start, session_id)
    WHERE correspondence = 'fulfilled';
