create table if not exists activity_response_metrics (
    id bigserial primary key,
    user_id text not null,
    strava_activity_id bigint not null,
    version text not null,
    computed_at timestamptz not null default now(),

    activity_type text,
    activity_date date,
    duration_s integer,
    intensity_factor double precision,
    intensity_band text,

    avg_power_w double precision,
    normalized_power_w double precision,
    avg_hr_bpm double precision,
    avg_power_to_hr double precision,
    normalized_power_to_hr double precision,
    aerobic_decoupling_pct double precision,

    rpe_score integer,
    session_rpe_load double precision,
    rpe_per_intensity_factor double precision,
    session_rpe_load_per_tss double precision,

    availability_json jsonb not null default '{}'::jsonb,
    baseline_json jsonb not null default '{}'::jsonb,
    explanation_json jsonb not null default '{}'::jsonb,

    constraint uq_activity_response_metrics
        unique (strava_activity_id, version),
    constraint chk_activity_response_metrics_rpe
        check (
            rpe_score is null
            or (version = 'v1' and rpe_score between 1 and 5)
            or (version <> 'v1' and rpe_score between 1 and 10)
        )
);

create index if not exists ix_activity_response_metrics_user_date
    on activity_response_metrics (user_id, activity_date desc);

create index if not exists ix_activity_response_metrics_comparable
    on activity_response_metrics (
        user_id,
        activity_type,
        intensity_band,
        version,
        activity_date desc
    );
