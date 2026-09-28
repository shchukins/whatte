-- The old activity_subjective_feedback rows and response v1 remain historical.
create table if not exists activity_rpe_observation (
    id bigserial primary key,
    user_id text not null,
    canonical_activity_id bigint not null,
    source text not null check (source in ('telegram', 'web', 'strava')),
    score integer not null check (score between 1 and 10),
    scale_version text not null default 'rpe_1_10'
        check (scale_version = 'rpe_1_10'),
    schema_version text not null default 'rpe_observation_v1'
        check (schema_version = 'rpe_observation_v1'),
    observed_at timestamptz,
    received_at timestamptz not null default now(),
    source_payload jsonb not null default '{}'::jsonb,
    unique (canonical_activity_id, source)
);

create index if not exists ix_activity_rpe_observation_user_activity
    on activity_rpe_observation (user_id, canonical_activity_id);

create table if not exists activity_rpe_resolution (
    canonical_activity_id bigint primary key,
    user_id text not null,
    effective_score integer check (effective_score between 1 and 10),
    effective_source text check (effective_source in ('telegram', 'web', 'strava')),
    disagreement boolean not null default false,
    resolved_at timestamptz not null default now(),
    check ((effective_score is null) = (effective_source is null))
);

-- The version constraint is conditional so old v1 rows remain valid.
alter table activity_response_metrics
    drop constraint if exists chk_activity_response_metrics_rpe;
alter table activity_response_metrics
    add constraint chk_activity_response_metrics_rpe
    check (
        rpe_score is null
        or (version = 'v1' and rpe_score between 1 and 5)
        or (version <> 'v1' and rpe_score between 1 and 10)
    );
