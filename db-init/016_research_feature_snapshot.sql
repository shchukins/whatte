create table if not exists research_feature_snapshot (
    id bigserial primary key,
    user_id text not null,
    local_date date not null,
    event_type text not null,
    reference_key text not null,
    feature_vector_version text not null,
    cutoff_at timestamptz not null,
    feature_json jsonb not null,
    content_fingerprint text not null,
    captured_at timestamptz not null default now(),
    constraint chk_research_feature_snapshot_event_type
        check (event_type in ('daily_readiness_delivery'))
);

create unique index if not exists uq_research_feature_snapshot_state
    on research_feature_snapshot (
        user_id,
        local_date,
        event_type,
        reference_key,
        content_fingerprint
    );

create index if not exists ix_research_feature_snapshot_user_date
    on research_feature_snapshot (user_id, local_date, captured_at, id);
