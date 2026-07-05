create table if not exists activity_subjective_feedback (
    id bigserial primary key,
    user_id text not null,
    strava_activity_id bigint not null,
    feedback_type text not null,
    feedback_value text not null,
    feedback_score integer not null,
    source text not null,
    context_json jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_activity_subjective_feedback_activity_type
        unique (strava_activity_id, feedback_type),
    constraint chk_activity_subjective_feedback_score
        check (feedback_score between 1 and 5)
);

create index if not exists ix_activity_subjective_feedback_user_created_at
    on activity_subjective_feedback (user_id, created_at desc);

create index if not exists ix_activity_subjective_feedback_activity_id
    on activity_subjective_feedback (strava_activity_id);
