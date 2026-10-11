-- Whatte V1: ordered historical schema; Flyway owns the transaction.
-- Do not execute on an existing database; adoption uses explicit baseline.

-- Source: sql/ingestion/sql_user_strava_connection.sql
create table if not exists user_strava_connection (
    id bigserial primary key,
    user_id text not null,
    strava_athlete_id bigint not null,
    access_token text not null,
    refresh_token text not null,
    expires_at timestamptz not null,
    scope text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists uq_user_strava_connection_user_id
    on user_strava_connection (user_id);

create unique index if not exists uq_user_strava_connection_strava_athlete_id
    on user_strava_connection (strava_athlete_id);

-- Source: sql/ingestion/sql_strava_webhook_event.sql
create table if not exists strava_webhook_event (
    id bigserial primary key,
    subscription_id bigint,
    owner_id bigint not null,
    object_type text not null,
    object_id bigint not null,
    aspect_type text not null,
    event_time timestamptz not null,
    updates jsonb,
    payload jsonb not null,
    received_at timestamptz not null default now(),
    status text not null default 'new',
    dedupe_key text not null,
    error_text text
);

create index if not exists ix_strava_webhook_event_received_at
    on strava_webhook_event (received_at desc);

create index if not exists ix_strava_webhook_event_owner_id
    on strava_webhook_event (owner_id);

create index if not exists ix_strava_webhook_event_object_id
    on strava_webhook_event (object_id);

alter table strava_webhook_event add constraint uq_strava_webhook_event_dedupe_key unique (dedupe_key);

-- Source: sql/ingestion/sql_strava_activity_raw.sql
create table if not exists strava_activity_raw (
    id bigserial primary key,
    user_id text not null,
    strava_athlete_id bigint not null,
    strava_activity_id bigint not null,
    activity_type text,
    name text,
    start_date timestamptz,
    timezone text,
    distance_m double precision,
    moving_time_s integer,
    elapsed_time_s integer,
    total_elevation_gain_m double precision,
    average_speed_mps double precision,
    max_speed_mps double precision,
    average_heartrate double precision,
    max_heartrate double precision,
    average_watts double precision,
    max_watts double precision,
    weighted_average_watts double precision,
    kilojoules double precision,
    trainer boolean,
    commute boolean,
    manual boolean,
    raw_json jsonb not null,
    fetched_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    is_deleted boolean not null default false,
    duplicate_of_activity_id bigint,
    is_excluded boolean not null default false,
    exclusion_reason text,
    duplicate_confidence double precision,
    duplicate_reason jsonb,
    duplicate_detected_at timestamptz,
    duplicate_detection_version text,
    deduplication_manual_override text,
    duplicate_candidate_activity_id bigint,
    constraint chk_strava_activity_raw_not_self_duplicate
        check (
            duplicate_of_activity_id is null
            or duplicate_of_activity_id <> strava_activity_id
        ),
    constraint chk_strava_activity_raw_duplicate_confidence
        check (
            duplicate_confidence is null
            or duplicate_confidence between 0.0 and 1.0
        ),
    constraint chk_strava_activity_raw_manual_override
        check (
            deduplication_manual_override is null
            or deduplication_manual_override in ('exclude', 'separate')
        )
);

create unique index if not exists uq_strava_activity_raw_activity_id
    on strava_activity_raw (strava_activity_id);

create index if not exists ix_strava_activity_raw_user_id_start_date
    on strava_activity_raw (user_id, start_date desc);

create index if not exists ix_strava_activity_raw_athlete_id_start_date
    on strava_activity_raw (strava_athlete_id, start_date desc);

create index if not exists ix_strava_activity_raw_user_dedup_candidates
    on strava_activity_raw (user_id, start_date)
    where is_deleted = false;

create index if not exists ix_strava_activity_raw_duplicate_of
    on strava_activity_raw (duplicate_of_activity_id)
    where duplicate_of_activity_id is not null;

create index if not exists ix_strava_activity_raw_excluded
    on strava_activity_raw (user_id, is_excluded, start_date);

-- Source: sql/ingestion/sql_healthkit_ingest_raw.sql
create table if not exists healthkit_ingest_raw (
    id bigserial primary key,
    user_id text not null,
    generated_at timestamptz not null,
    timezone text not null,
    payload_json jsonb not null,
    received_at timestamptz not null default now()
);

create index if not exists idx_healthkit_ingest_raw_user_id
    on healthkit_ingest_raw(user_id);

create index if not exists idx_healthkit_ingest_raw_received_at
    on healthkit_ingest_raw(received_at desc);

-- Source: sql/ingestion/sql_strava_activity_ingest_job.sql
create table if not exists strava_activity_ingest_job (
    id bigserial primary key,
    webhook_event_id bigint references strava_webhook_event(id) on delete set null,
    user_id text not null,
    strava_athlete_id bigint not null,
    strava_activity_id bigint not null,
    reason text not null,
    status text not null default 'pending',
    attempt_count integer not null default 0,
    scheduled_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz,
    last_error text,
    created_at timestamptz not null default now()
);

create index if not exists ix_strava_activity_ingest_job_status_scheduled_at
    on strava_activity_ingest_job (status, scheduled_at);

create index if not exists ix_strava_activity_ingest_job_activity_id
    on strava_activity_ingest_job (strava_activity_id);

create unique index if not exists uq_strava_activity_ingest_job_active
    on strava_activity_ingest_job (strava_activity_id)
    where status in ('pending', 'running');

-- Source: sql/ingestion/sql_strava_activity_stream_raw.sql
create table if not exists strava_activity_stream_raw (
    id bigserial primary key,
    strava_activity_id bigint not null,
    stream_type text not null,
    series_type text,
    resolution text,
    original_size integer,
    data_json jsonb not null,
    fetched_at timestamptz not null default now(),

    constraint uq_strava_activity_stream_raw unique (strava_activity_id, stream_type)
);

create index if not exists ix_strava_activity_stream_raw_activity_id
    on strava_activity_stream_raw (strava_activity_id);

-- Source: sql/scratch/sql_user_training_profile.sql
create table if not exists user_training_profile (
    id bigserial primary key,
    user_id text not null,
    effective_from date not null,
    ftp_watts double precision,
    hr_max integer,
    hr_rest integer,
    hr_threshold integer,

    power_z1_upper double precision,
    power_z2_upper double precision,
    power_z3_upper double precision,
    power_z4_upper double precision,
    power_z5_upper double precision,
    power_z6_upper double precision,

    hr_z1_upper integer,
    hr_z2_upper integer,
    hr_z3_upper integer,
    hr_z4_upper integer,

    source text,
    created_at timestamptz not null default now(),

    constraint uq_user_training_profile unique (user_id, effective_from)
);

create index if not exists ix_user_training_profile_user_id_effective_from
    on user_training_profile (user_id, effective_from desc);

-- Source: sql/health/sql_health_sleep_night.sql
create table if not exists health_sleep_night (
    id bigserial primary key,
    user_id text not null,
    wake_date date not null,
    sleep_start_at timestamptz not null,
    sleep_end_at timestamptz not null,
    total_sleep_minutes double precision not null,
    awake_minutes double precision not null,
    core_minutes double precision not null,
    rem_minutes double precision not null,
    deep_minutes double precision not null,
    in_bed_minutes double precision,
    source text not null default 'healthkit',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists uq_health_sleep_night_user_wake_date
    on health_sleep_night(user_id, wake_date);

create index if not exists idx_health_sleep_night_user_wake_date
    on health_sleep_night(user_id, wake_date desc);

-- Source: sql/health/sql_health_resting_hr_daily.sql
create table if not exists health_resting_hr_daily (
    id bigserial primary key,
    user_id text not null,
    date date not null,
    bpm double precision not null,
    source text not null default 'healthkit',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists uq_health_resting_hr_daily_user_date
    on health_resting_hr_daily(user_id, date);

create index if not exists idx_health_resting_hr_daily_user_date
    on health_resting_hr_daily(user_id, date desc);

-- Source: sql/health/sql_health_hrv_sample.sql
create table if not exists health_hrv_sample (
    id bigserial primary key,
    user_id text not null,
    sample_start_at timestamptz not null,
    value_ms double precision not null,
    source text not null default 'healthkit',
    created_at timestamptz not null default now()
);

create unique index if not exists uq_health_hrv_sample_user_start_at
    on health_hrv_sample(user_id, sample_start_at);

create index if not exists idx_health_hrv_sample_user_start_at
    on health_hrv_sample(user_id, sample_start_at desc);

-- Source: sql/health/sql_health_weight_measurement.sql
create table if not exists health_weight_measurement (
    id bigserial primary key,
    user_id text not null,
    measured_at timestamptz not null,
    kilograms double precision not null,
    source text not null default 'healthkit',
    created_at timestamptz not null default now()
);

create unique index if not exists uq_health_weight_measurement_user_measured_at
    on health_weight_measurement(user_id, measured_at);

create index if not exists idx_health_weight_measurement_user_measured_at
    on health_weight_measurement(user_id, measured_at desc);

-- Source: sql/analytics/sql_activity_metrics.sql
create table if not exists activity_metrics (
    id bigserial primary key,
    user_id text not null,
    strava_activity_id bigint not null,
    computed_at timestamptz not null default now(),
    version text not null default 'v1',

    duration_s integer,
    moving_time_s integer,
    distance_m double precision,
    elevation_gain_m double precision,

    avg_speed_mps double precision,
    max_speed_mps double precision,

    avg_heartrate double precision,
    max_heartrate double precision,

    avg_power double precision,
    max_power double precision,
    weighted_avg_power double precision,

    normalized_power double precision,
    intensity_factor double precision,
    variability_index double precision,

    work_kj double precision,
    trimp double precision,
    tss double precision,
    hr_drift_pct double precision,

    time_in_power_z1_s integer,
    time_in_power_z2_s integer,
    time_in_power_z3_s integer,
    time_in_power_z4_s integer,
    time_in_power_z5_s integer,
    time_in_power_z6_s integer,
    time_in_power_z7_s integer,

    time_in_hr_z1_s integer,
    time_in_hr_z2_s integer,
    time_in_hr_z3_s integer,
    time_in_hr_z4_s integer,
    time_in_hr_z5_s integer,

    raw_json jsonb,

    constraint uq_activity_metrics unique (strava_activity_id, version)
);

create index if not exists ix_activity_metrics_user_id
    on activity_metrics (user_id);

create index if not exists ix_activity_metrics_activity_id
    on activity_metrics (strava_activity_id);

-- Source: sql/analytics/sql_activity_response_metrics.sql
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

-- Source: sql/analytics/sql_daily_training_load.sql
create table if not exists daily_training_load (
    id bigserial primary key,

    user_id text not null,
    date date not null,

    activities_count integer,
    duration_s integer,
    distance_m double precision,
    elevation_gain_m double precision,

    work_kj double precision,
    tss double precision,

    computed_at timestamptz not null default now(),

    constraint uq_daily_training_load unique (user_id, date)
);

create index if not exists ix_daily_training_load_user_date
on daily_training_load(user_id, date desc);

-- Source: sql/analytics/sql_daily_fitness_state.sql
create table if not exists daily_fitness_state (
    id bigserial primary key,

    user_id text not null,
    date date not null,

    daily_tss double precision not null default 0,
    fitness_signal double precision not null default 0,
    fatigue_signal double precision not null default 0,
    freshness_signal double precision not null default 0,

    model_version text not null default 'v1',
    computed_at timestamptz not null default now(),

    constraint uq_daily_fitness_state unique (user_id, date, model_version)
);

create index if not exists ix_daily_fitness_state_user_date
    on daily_fitness_state (user_id, date desc);

-- Source: sql/health/sql_health_recovery_daily.sql
create table if not exists health_recovery_daily (
    id bigserial primary key,
    user_id text not null,
    date date not null,
    sleep_minutes double precision,
    awake_minutes double precision,
    rem_minutes double precision,
    deep_minutes double precision,
    resting_hr_bpm double precision,
    hrv_daily_median_ms double precision,
    weight_kg double precision,
    recovery_score_simple double precision,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists uq_health_recovery_daily_user_date
    on health_recovery_daily(user_id, date);

create index if not exists idx_health_recovery_daily_user_date
    on health_recovery_daily(user_id, date desc);

-- Source: sql/analytics/sql_load_state_daily_v2.sql
create table if not exists load_state_daily_v2 (
    id bigserial primary key,
    user_id text not null,
    date date not null,
    tss double precision not null default 0,
    load_input_nonlinear double precision,
    fitness double precision,
    fatigue_fast double precision,
    fatigue_slow double precision,
    fatigue_total double precision,
    freshness double precision,
    version text not null default 'v2',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists uq_load_state_daily_v2_user_date_version
    on load_state_daily_v2(user_id, date, version);

create index if not exists idx_load_state_daily_v2_user_date
    on load_state_daily_v2(user_id, date desc);

-- Source: sql/analytics/sql_readiness_daily.sql
create table if not exists readiness_daily (
    id bigserial primary key,
    user_id text not null,
    date date not null,
    freshness double precision,
    recovery_score_simple double precision,
    readiness_score_raw double precision,
    readiness_score double precision,
    good_day_probability double precision,
    status_text text,
    explanation_json jsonb,
    version text not null default 'v2',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists uq_readiness_daily_user_date_version
    on readiness_daily(user_id, date, version);

create index if not exists idx_readiness_daily_user_date
    on readiness_daily(user_id, date desc);

-- Source: db-init/001_init.sql
CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Source: db-init/002_activity_subjective_feedback.sql
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

-- Source: sql/health/sql_health_recovery_daily_add_explanation_json.sql
alter table health_recovery_daily
add column if not exists recovery_explanation_json jsonb;

-- Source: db-init/003_subjective_feedback_extensible.sql
alter table if exists activity_subjective_feedback
    add column if not exists activity_date date,
    add column if not exists feedback_schema_version text,
    add column if not exists feedback_payload jsonb;

update activity_subjective_feedback
set feedback_schema_version = coalesce(feedback_schema_version, 'v1'),
    feedback_payload = coalesce(feedback_payload, '{}'::jsonb)
where feedback_schema_version is null
   or feedback_payload is null;

alter table activity_subjective_feedback
    alter column feedback_schema_version set default 'v1_extensible',
    alter column feedback_schema_version set not null,
    alter column feedback_payload set default '{}'::jsonb,
    alter column feedback_payload set not null;

alter table activity_subjective_feedback
    drop constraint if exists chk_activity_subjective_feedback_score;

-- Source: db-init/004_next_day_recovery_feedback.sql
alter table if exists activity_subjective_feedback
    alter column strava_activity_id drop not null;

alter table if exists activity_subjective_feedback
    drop constraint if exists uq_activity_subjective_feedback_activity_type;

create unique index if not exists uq_activity_subjective_feedback_activity_type
    on activity_subjective_feedback (strava_activity_id, feedback_type)
    where strava_activity_id is not null;

create unique index if not exists uq_activity_subjective_feedback_user_date_type_null_activity
    on activity_subjective_feedback (user_id, activity_date, feedback_type)
    where strava_activity_id is null;

-- Source: db-init/005_subjective_feedback_prompt_log.sql
create table if not exists subjective_feedback_prompt_log (
    id bigserial primary key,
    user_id text not null,
    prompt_type text not null,
    target_date date not null,
    sent_at timestamptz,
    source text not null,
    delivery_status text not null,
    telegram_message_id bigint,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_subjective_feedback_prompt_log_user_type_date
        unique (user_id, prompt_type, target_date),
    constraint chk_subjective_feedback_prompt_log_status
        check (delivery_status in ('pending', 'sent', 'failed'))
);

create index if not exists ix_subjective_feedback_prompt_log_target_date
    on subjective_feedback_prompt_log (target_date desc, prompt_type);

create index if not exists ix_subjective_feedback_prompt_log_user_created_at
    on subjective_feedback_prompt_log (user_id, created_at desc);

-- Source: db-init/006_notification_log.sql (verified production variant).
-- Production predates this file: preserve its notification columns and indexes.
create table notification_log (
    id bigserial primary key,
    user_id text not null,
    notification_type text not null,
    notification_date date not null,
    related_activity_id bigint,
    sent_at timestamptz not null default now(),
    payload_json jsonb
);
create unique index uq_notification_log_user_type_date
    on notification_log (user_id, notification_type, notification_date);
create unique index uq_notification_log_daily
    on notification_log (user_id, notification_type, notification_date);
create unique index uq_notification_log_activity
    on notification_log (user_id, notification_type, related_activity_id)
    where related_activity_id is not null;

-- Source: db-init/007_indoor_activity_deduplication.sql
alter table if exists strava_activity_raw
    add column if not exists duplicate_of_activity_id bigint,
    add column if not exists is_excluded boolean not null default false,
    add column if not exists exclusion_reason text,
    add column if not exists duplicate_confidence double precision,
    add column if not exists duplicate_reason jsonb,
    add column if not exists duplicate_detected_at timestamptz,
    add column if not exists duplicate_detection_version text,
    add column if not exists deduplication_manual_override text,
    add column if not exists duplicate_candidate_activity_id bigint;

do $$
begin
    if to_regclass('public.strava_activity_raw') is not null and not exists (
        select 1
        from pg_constraint
        where conname = 'chk_strava_activity_raw_not_self_duplicate'
    ) then
        alter table strava_activity_raw
            add constraint chk_strava_activity_raw_not_self_duplicate
            check (
                duplicate_of_activity_id is null
                or duplicate_of_activity_id <> strava_activity_id
            );
    end if;

    if to_regclass('public.strava_activity_raw') is not null and not exists (
        select 1
        from pg_constraint
        where conname = 'chk_strava_activity_raw_duplicate_confidence'
    ) then
        alter table strava_activity_raw
            add constraint chk_strava_activity_raw_duplicate_confidence
            check (
                duplicate_confidence is null
                or duplicate_confidence between 0.0 and 1.0
            );
    end if;

    if to_regclass('public.strava_activity_raw') is not null and not exists (
        select 1
        from pg_constraint
        where conname = 'chk_strava_activity_raw_manual_override'
    ) then
        alter table strava_activity_raw
            add constraint chk_strava_activity_raw_manual_override
            check (
                deduplication_manual_override is null
                or deduplication_manual_override in ('exclude', 'separate')
            );
    end if;

    if to_regclass('public.strava_activity_raw') is not null then
        execute 'create index if not exists ix_strava_activity_raw_user_dedup_candidates
            on strava_activity_raw (user_id, start_date)
            where is_deleted = false';
        execute 'create index if not exists ix_strava_activity_raw_duplicate_of
            on strava_activity_raw (duplicate_of_activity_id)
            where duplicate_of_activity_id is not null';
        execute 'create index if not exists ix_strava_activity_raw_excluded
            on strava_activity_raw (user_id, is_excluded, start_date)';
    end if;
end
$$;

create table if not exists activity_delivery_log (
    id bigserial primary key,
    user_id text not null,
    activity_id bigint not null,
    delivery_type text not null,
    delivery_status text not null,
    telegram_message_id bigint,
    payload_json jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint chk_activity_delivery_log_type
        check (delivery_type in ('training_processed', 'post_ride_rpe')),
    constraint chk_activity_delivery_log_status
        check (delivery_status in ('claimed', 'sent', 'failed'))
);

create unique index if not exists uq_activity_delivery_log_activity_type
    on activity_delivery_log (activity_id, delivery_type);

create index if not exists ix_activity_delivery_log_user_created_at
    on activity_delivery_log (user_id, created_at desc);

alter table if exists activity_subjective_feedback
    add column if not exists canonical_activity_id bigint;

update activity_subjective_feedback
set canonical_activity_id = strava_activity_id
where canonical_activity_id is null
  and strava_activity_id is not null;

create unique index if not exists uq_activity_subjective_feedback_canonical_type
    on activity_subjective_feedback (canonical_activity_id, feedback_type)
    where canonical_activity_id is not null;

create index if not exists ix_activity_subjective_feedback_canonical_activity_id
    on activity_subjective_feedback (canonical_activity_id)
    where canonical_activity_id is not null;

-- Source: db-init/008_daily_readiness_delivery_lifecycle.sql
alter table if exists notification_log
    add column if not exists recovery_date date,
    add column if not exists freshness_status text,
    add column if not exists delivery_status text,
    add column if not exists telegram_chat_id text,
    add column if not exists telegram_message_id bigint,
    add column if not exists sent_at timestamptz,
    add column if not exists updated_at timestamptz not null default now(),
    add column if not exists content_fingerprint text;

update notification_log
set recovery_date = coalesce(
        recovery_date,
        nullif(payload_json->'data_freshness'->>'recovery_date', '')::date
    ),
    freshness_status = coalesce(
        freshness_status,
        payload_json->'data_freshness'->>'state',
        'missing'
    ),
    delivery_status = coalesce(
        delivery_status,
        payload_json->>'delivery_state',
        'sent'
    ),
    sent_at = case
        when coalesce(payload_json->>'delivery_state', 'sent') = 'sent'
            then coalesce(sent_at, updated_at, now())
        else sent_at
    end,
    updated_at = coalesce(updated_at, sent_at, now())
where notification_type = 'daily_readiness';

do $$
begin
    if to_regclass('public.notification_log') is not null and not exists (
        select 1
        from pg_constraint
        where conname = 'chk_notification_log_daily_freshness'
          and conrelid = 'public.notification_log'::regclass
    ) then
        alter table notification_log
            add constraint chk_notification_log_daily_freshness
            check (
                notification_type <> 'daily_readiness'
                or freshness_status in ('fresh', 'stale', 'missing')
            );
    end if;

    if to_regclass('public.notification_log') is not null and not exists (
        select 1
        from pg_constraint
        where conname = 'chk_notification_log_daily_delivery_status'
          and conrelid = 'public.notification_log'::regclass
    ) then
        alter table notification_log
            add constraint chk_notification_log_daily_delivery_status
            check (
                notification_type <> 'daily_readiness'
                or delivery_status in (
                    'claimed',
                    'sent',
                    'updating',
                    'updated',
                    'superseded',
                    'failed'
                )
            );
    end if;
end
$$;

-- Source: db-init/009_activity_response_metrics.sql
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
        check (rpe_score is null or rpe_score between 1 and 5)
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

-- Source: db-init/010_decision_context_snapshot.sql
create table if not exists decision_context_snapshot (
    id bigserial primary key,
    user_id text not null,
    snapshot_date date not null,
    event_type text not null,
    reference_key text not null,
    model_version text not null,
    readiness_score double precision,
    good_day_probability double precision,
    recommendation text,
    status_text text,
    snapshot_json jsonb not null,
    content_fingerprint text not null,
    captured_at timestamptz not null default now(),
    constraint chk_decision_context_snapshot_event_type
        check (event_type in (
            'daily_readiness_delivery',
            'recovery_checkin_before',
            'recovery_checkin_after'
        ))
);

create unique index if not exists uq_decision_context_snapshot_event_state
    on decision_context_snapshot (
        user_id,
        snapshot_date,
        event_type,
        reference_key,
        content_fingerprint
    );

create index if not exists ix_decision_context_snapshot_user_date
    on decision_context_snapshot (user_id, snapshot_date, captured_at);

-- Source: db-init/011_user_profile.sql
-- Independent dated inputs: changing weight never copies or changes FTP.
create table if not exists user_profile_value (
    user_id text not null,
    metric text not null check (metric in ('ftp', 'weight')),
    effective_from date not null,
    value numeric not null,
    needs_recompute boolean not null default false,
    updated_at timestamptz not null default now(),
    primary key (user_id, metric, effective_from),
    check ((metric = 'ftp' and value between 1 and 1000)
        or (metric = 'weight' and value between 1 and 500))
);

-- Some empty installations have not provisioned the legacy profile table.
do $$ begin
    if to_regclass('user_training_profile') is not null then
        insert into user_profile_value (user_id, metric, effective_from, value)
        select user_id, 'ftp', effective_from, ftp_watts
        from user_training_profile where ftp_watts > 0 and ftp_watts <= 1000
        on conflict do nothing;
    end if;
end $$;

-- Source: db-init/012_rpe_observations.sql
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

-- Source: db-init/013_manual_physiology_observations.sql
-- Current optional manual physiology for one configured local calendar date.
-- NULL is an explicit unavailable value; it is never converted to zero.
create table if not exists manual_physiology_observation (
    id bigserial primary key,
    user_id text not null,
    local_date date not null,
    sleep_duration_minutes integer
        check (sleep_duration_minutes between 0 and 1440),
    sleep_quality integer check (sleep_quality between 1 and 5),
    hrv_ms double precision check (hrv_ms > 0 and hrv_ms <= 500),
    resting_hr_bpm double precision
        check (resting_hr_bpm >= 20 and resting_hr_bpm <= 250),
    source text not null check (source in ('telegram', 'web', 'import')),
    observed_at timestamptz,
    schema_version text not null default 'manual_physiology_observation_v1'
        check (schema_version = 'manual_physiology_observation_v1'),
    revision integer not null default 1 check (revision >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, local_date)
);

create index if not exists ix_manual_physiology_observation_user_date
    on manual_physiology_observation (user_id, local_date desc);

-- Full snapshots make edits auditable without turning the current table into
-- an event log. changed_fields identifies which values the source submitted.
create table if not exists manual_physiology_observation_revision (
    id bigserial primary key,
    observation_id bigint not null
        references manual_physiology_observation(id) on delete restrict,
    user_id text not null,
    local_date date not null,
    revision integer not null check (revision >= 1),
    sleep_duration_minutes integer
        check (sleep_duration_minutes between 0 and 1440),
    sleep_quality integer check (sleep_quality between 1 and 5),
    hrv_ms double precision check (hrv_ms > 0 and hrv_ms <= 500),
    resting_hr_bpm double precision
        check (resting_hr_bpm >= 20 and resting_hr_bpm <= 250),
    source text not null check (source in ('telegram', 'web', 'import')),
    observed_at timestamptz,
    schema_version text not null
        check (schema_version = 'manual_physiology_observation_v1'),
    changed_fields text[] not null,
    received_at timestamptz not null default now(),
    unique (observation_id, revision)
);

create index if not exists ix_manual_physiology_revision_user_date
    on manual_physiology_observation_revision (
        user_id,
        local_date desc,
        revision desc
    );

-- Source: db-init/014_telegram_physiology_checkin.sql
-- Ephemeral Telegram input state for optional manual physiology collection.
-- Observations remain in manual_physiology_observation; this table contains no
-- physiology values and only makes the multi-message UI deterministic.
create table if not exists telegram_physiology_checkin_session (
    id bigserial primary key,
    user_id text not null,
    local_date date not null,
    telegram_chat_id text not null,
    session_token text not null,
    status text not null,
    current_field text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_telegram_physiology_checkin_session_user_date
        unique (user_id, local_date),
    constraint uq_telegram_physiology_checkin_session_token
        unique (session_token),
    constraint chk_telegram_physiology_checkin_session_status
        check (status in ('active', 'processing', 'skipped', 'complete')),
    constraint chk_telegram_physiology_checkin_session_field
        check (current_field is null or current_field in (
            'sleep_duration_minutes', 'sleep_quality', 'hrv_ms', 'resting_hr_bpm'
        ))
);

create index if not exists ix_telegram_physiology_checkin_session_active
    on telegram_physiology_checkin_session (telegram_chat_id, local_date desc)
    where status = 'active';

-- Source: db-init/015_personal_physiology_features.sql
-- Versioned, manual-observation-only physiology features for research and
-- future feature-vector construction. This table is not a readiness input.
create table if not exists personal_physiology_feature_daily (
    user_id text not null,
    local_date date not null,
    source_observation_id bigint not null
        references manual_physiology_observation(id) on delete restrict,
    source_revision integer not null check (source_revision >= 1),
    observed_at timestamptz,
    source_updated_at timestamptz not null,
    source_staleness text not null
        check (source_staleness in ('current_local_date', 'stale', 'late', 'unknown')),
    feature_version text not null check (length(feature_version) > 0),
    baseline_window_days integer not null check (baseline_window_days > 0),
    baseline_min_observations integer not null check (baseline_min_observations > 0),

    hrv_observation_count integer not null check (hrv_observation_count >= 0),
    hrv_availability text not null check (hrv_availability in ('available', 'unavailable')),
    hrv_baseline_state text not null check (hrv_baseline_state in ('unavailable', 'immature', 'mature')),
    hrv_baseline_ms double precision,
    hrv_ratio double precision,
    hrv_deviation double precision,

    resting_hr_observation_count integer not null check (resting_hr_observation_count >= 0),
    resting_hr_availability text not null check (resting_hr_availability in ('available', 'unavailable')),
    resting_hr_baseline_state text not null check (resting_hr_baseline_state in ('unavailable', 'immature', 'mature')),
    resting_hr_baseline_bpm double precision,
    resting_hr_delta_bpm double precision,

    sleep_duration_observation_count integer not null check (sleep_duration_observation_count >= 0),
    sleep_duration_availability text not null check (sleep_duration_availability in ('available', 'unavailable')),
    sleep_duration_baseline_state text not null check (sleep_duration_baseline_state in ('unavailable', 'immature', 'mature')),
    sleep_duration_baseline_minutes double precision,
    sleep_duration_deviation_minutes double precision,
    sleep_duration_debt_minutes double precision,
    computed_at timestamptz not null default now(),
    primary key (user_id, local_date, feature_version),
    check (hrv_baseline_state <> 'mature' or hrv_baseline_ms is not null),
    check (resting_hr_baseline_state <> 'mature' or resting_hr_baseline_bpm is not null),
    check (sleep_duration_baseline_state <> 'mature' or sleep_duration_baseline_minutes is not null)
);

create index if not exists ix_personal_physiology_feature_user_date
    on personal_physiology_feature_daily (user_id, local_date desc, feature_version);

-- Source: db-init/016_research_feature_snapshot.sql
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

-- Source: db-init/017_decision_context_snapshot_events.sql
alter table decision_context_snapshot
    drop constraint if exists chk_decision_context_snapshot_event_type;

alter table decision_context_snapshot
    add constraint chk_decision_context_snapshot_event_type
        check (event_type in (
            'daily_readiness_delivery',
            'recovery_checkin_before',
            'recovery_checkin_after',
            'post_activity_state',
            'post_ride_feedback'
        ));

-- Source: db-init/018_research_experiment.sql
-- Research-only audit records. These rows describe offline experiments; they
-- must never contain source payloads, feature vectors, predictions, or mutate
-- user-facing production state.
create table if not exists research_experiment (
    id bigserial primary key,
    experiment_id text not null unique,
    parent_experiment_id text references research_experiment (experiment_id),
    baseline_experiment_id text references research_experiment (experiment_id),
    hypothesis text not null,
    candidate_model_version text not null,
    candidate_config jsonb not null,
    candidate_config_hash text not null,
    dataset_version text not null,
    dataset_hash text not null,
    dataset_partition text not null,
    evaluator_version text not null,
    evaluator_specification_hash text not null,
    status text not null,
    metrics_json jsonb,
    failure_reason text,
    failure_log_reference text,
    provider_metadata jsonb,
    created_at timestamptz not null default now(),
    started_at timestamptz not null,
    finished_at timestamptz,
    execution_duration_ms bigint,
    constraint chk_research_experiment_id_nonempty
        check (length(btrim(experiment_id)) > 0),
    constraint chk_research_experiment_parent_not_self
        check (parent_experiment_id is null or parent_experiment_id <> experiment_id),
    constraint chk_research_experiment_baseline_not_self
        check (baseline_experiment_id is null or baseline_experiment_id <> experiment_id),
    constraint chk_research_experiment_candidate_config_object
        check (jsonb_typeof(candidate_config) = 'object'),
    constraint chk_research_experiment_metrics_object
        check (metrics_json is null or jsonb_typeof(metrics_json) = 'object'),
    constraint chk_research_experiment_provider_metadata_object
        check (provider_metadata is null or jsonb_typeof(provider_metadata) = 'object'),
    constraint chk_research_experiment_partition
        check (dataset_partition in ('train', 'validation', 'test')),
    constraint chk_research_experiment_status
        check (status in ('running', 'rejected', 'candidate', 'failed', 'promoted')),
    constraint chk_research_experiment_time_order
        check (created_at <= started_at and (finished_at is null or started_at <= finished_at)),
    constraint chk_research_experiment_terminal_state
        check (
            (status = 'running'
                and finished_at is null
                and execution_duration_ms is null
                and metrics_json is null
                and failure_reason is null
                and failure_log_reference is null)
            or
            (status in ('candidate', 'rejected', 'promoted')
                and finished_at is not null
                and execution_duration_ms is not null
                and execution_duration_ms >= 0
                and metrics_json is not null
                and failure_reason is null
                and failure_log_reference is null)
            or
            (status = 'failed'
                and finished_at is not null
                and execution_duration_ms is not null
                and execution_duration_ms >= 0
                and metrics_json is null
                and failure_reason is not null
                and length(btrim(failure_reason)) > 0)
        )
);

create index if not exists ix_research_experiment_status_created
    on research_experiment (status, created_at, id);

create index if not exists ix_research_experiment_parent
    on research_experiment (parent_experiment_id)
    where parent_experiment_id is not null;

create or replace function protect_research_experiment_audit_log()
returns trigger
language plpgsql
as $$
begin
    if tg_op = 'INSERT' then
        if new.status <> 'running' then
            raise exception 'research experiment must be created as running';
        end if;
        return new;
    end if;

    if tg_op = 'DELETE' then
        raise exception 'research experiment audit rows cannot be deleted';
    end if;

    if old.status <> 'running' then
        raise exception 'terminal research experiment rows are immutable';
    end if;

    if new.status not in ('candidate', 'rejected', 'failed') then
        raise exception 'research experiment must transition from running to candidate, rejected, or failed';
    end if;

    if new.experiment_id is distinct from old.experiment_id
       or new.parent_experiment_id is distinct from old.parent_experiment_id
       or new.baseline_experiment_id is distinct from old.baseline_experiment_id
       or new.hypothesis is distinct from old.hypothesis
       or new.candidate_model_version is distinct from old.candidate_model_version
       or new.candidate_config is distinct from old.candidate_config
       or new.candidate_config_hash is distinct from old.candidate_config_hash
       or new.dataset_version is distinct from old.dataset_version
       or new.dataset_hash is distinct from old.dataset_hash
       or new.dataset_partition is distinct from old.dataset_partition
       or new.evaluator_version is distinct from old.evaluator_version
       or new.evaluator_specification_hash is distinct from old.evaluator_specification_hash
       or new.provider_metadata is distinct from old.provider_metadata
       or new.created_at is distinct from old.created_at
       or new.started_at is distinct from old.started_at then
        raise exception 'research experiment input metadata is immutable';
    end if;

    return new;
end;
$$;

drop trigger if exists trg_protect_research_experiment_audit_log on research_experiment;
create trigger trg_protect_research_experiment_audit_log
before insert or update or delete on research_experiment
for each row execute function protect_research_experiment_audit_log();

-- Source: db-init/019_research_execution_metadata.sql
-- Nullable for existing #135 rows; metrics_json remains evaluator output only.
alter table research_experiment add column if not exists execution_metadata jsonb;
do $$
begin
    if not exists (select 1 from pg_constraint
                   where conrelid = 'research_experiment'::regclass
                     and conname = 'chk_research_execution_metadata') then
        alter table research_experiment add constraint chk_research_execution_metadata
        check (execution_metadata is null or
               (status <> 'running' and jsonb_typeof(execution_metadata) = 'object'));
    end if;
end;
$$;

-- This NOLOGIN role is only a permission group. Provision a dedicated LOGIN
-- externally with no other memberships, ownership, or elevated attributes.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'whatte_research_writer') then
        create role whatte_research_writer nologin nosuperuser nocreatedb
            nocreaterole noreplication nobypassrls;
    end if;
end;
$$;
grant usage on schema public to whatte_research_writer;
grant select on research_experiment to whatte_research_writer;
grant insert (experiment_id, parent_experiment_id, baseline_experiment_id,
    hypothesis, candidate_model_version, candidate_config, candidate_config_hash,
    dataset_version, dataset_hash, dataset_partition, evaluator_version,
    evaluator_specification_hash, status, provider_metadata, created_at, started_at)
    on research_experiment to whatte_research_writer;
grant update (status, finished_at, execution_duration_ms, metrics_json,
    failure_reason, failure_log_reference, execution_metadata)
    on research_experiment to whatte_research_writer;
grant usage on sequence research_experiment_id_seq to whatte_research_writer;
-- Existing lifecycle trigger blocks deletion and modification of terminal rows.

-- Source: db-init/020_user_profile_hr_max.sql
-- Extend the independent dated profile; never derive zones from HR max.

alter table user_profile_value
    drop constraint if exists user_profile_value_metric_check,
    drop constraint if exists user_profile_value_check;
alter table user_profile_value
    add constraint user_profile_value_metric_check
        check (metric in ('ftp', 'hr_max', 'weight')),
    add constraint user_profile_value_check
        check ((metric = 'ftp' and value between 1 and 1000)
            or (metric = 'weight' and value between 1 and 500)
            or (metric = 'hr_max' and value between 1 and 250 and value = trunc(value)));

-- Preserve legacy history without overwriting an existing manual correction.
-- HR max is provenance only; backfill does not recalculate stored metrics.
do $$ begin
    if to_regclass('user_training_profile') is not null then
        insert into user_profile_value (user_id, metric, effective_from, value)
        select user_id, 'hr_max', effective_from, hr_max
        from user_training_profile where hr_max between 1 and 250
        on conflict do nothing;
    end if;
end $$;


-- Preserved auxiliary production objects, catalog-only export (no rows).
-- vector; Type: EXTENSION; Schema: -; Owner: -
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

-- EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';

-- daily_state; Type: VIEW; Schema: analytics; Owner: -
CREATE SCHEMA analytics;

CREATE VIEW analytics.daily_state AS
 WITH days AS (
         SELECT readiness_daily.user_id,
            readiness_daily.date
           FROM public.readiness_daily
        UNION
         SELECT health_recovery_daily.user_id,
            health_recovery_daily.date
           FROM public.health_recovery_daily
        UNION
         SELECT load_state_daily_v2.user_id,
            load_state_daily_v2.date
           FROM public.load_state_daily_v2
        )
 SELECT d.user_id,
    d.date,
    r.readiness_score,
    r.good_day_probability,
    r.status_text AS readiness_status,
    r.freshness AS readiness_freshness,
    r.recovery_score_simple AS readiness_recovery_score,
    r.version AS readiness_version,
    rec.sleep_minutes,
    rec.awake_minutes,
    rec.rem_minutes,
    rec.deep_minutes,
    rec.resting_hr_bpm,
    rec.hrv_daily_median_ms,
    rec.weight_kg,
    rec.recovery_score_simple,
    COALESCE(t.activities_count, 0) AS activities_count,
    COALESCE(t.duration_s, 0) AS training_duration_s,
    COALESCE(t.distance_m, (0)::double precision) AS distance_m,
    COALESCE(t.elevation_gain_m, (0)::double precision) AS elevation_gain_m,
    COALESCE(t.work_kj, (0)::double precision) AS work_kj,
    COALESCE(t.tss, (0)::double precision) AS daily_tss,
    l.load_input_nonlinear,
    l.fitness,
    l.fatigue_fast,
    l.fatigue_slow,
    l.fatigue_total,
    l.freshness,
    l.version AS load_model_version,
        CASE
            WHEN ((rec.sleep_minutes + rec.awake_minutes) > (0)::double precision) THEN (((100.0)::double precision * rec.sleep_minutes) / (rec.sleep_minutes + rec.awake_minutes))
            ELSE NULL::double precision
        END AS sleep_efficiency_pct,
        CASE
            WHEN (rec.sleep_minutes > (0)::double precision) THEN (((100.0)::double precision * rec.deep_minutes) / rec.sleep_minutes)
            ELSE NULL::double precision
        END AS deep_sleep_pct,
        CASE
            WHEN (rec.sleep_minutes > (0)::double precision) THEN (((100.0)::double precision * rec.rem_minutes) / rec.sleep_minutes)
            ELSE NULL::double precision
        END AS rem_sleep_pct
   FROM ((((days d
     LEFT JOIN public.readiness_daily r ON (((r.user_id = d.user_id) AND (r.date = d.date))))
     LEFT JOIN public.health_recovery_daily rec ON (((rec.user_id = d.user_id) AND (rec.date = d.date))))
     LEFT JOIN public.daily_training_load t ON (((t.user_id = d.user_id) AND (t.date = d.date))))
     LEFT JOIN public.load_state_daily_v2 l ON (((l.user_id = d.user_id) AND (l.date = d.date))));

-- document; Type: TABLE; Schema: public; Owner: -
CREATE TABLE public.document (
    id bigint NOT NULL,
    source text NOT NULL,
    external_id text,
    title text NOT NULL,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- document_chunk; Type: TABLE; Schema: public; Owner: -
CREATE TABLE public.document_chunk (
    id bigint NOT NULL,
    document_id bigint NOT NULL,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    embedding public.vector(768),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- document_chunk_id_seq; Type: SEQUENCE; Schema: public; Owner: -
CREATE SEQUENCE public.document_chunk_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- document_chunk_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
ALTER SEQUENCE public.document_chunk_id_seq OWNED BY public.document_chunk.id;

-- document_id_seq; Type: SEQUENCE; Schema: public; Owner: -
CREATE SEQUENCE public.document_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- document_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
ALTER SEQUENCE public.document_id_seq OWNED BY public.document.id;

-- document id; Type: DEFAULT; Schema: public; Owner: -
ALTER TABLE ONLY public.document ALTER COLUMN id SET DEFAULT nextval('public.document_id_seq'::regclass);

-- document_chunk id; Type: DEFAULT; Schema: public; Owner: -
ALTER TABLE ONLY public.document_chunk ALTER COLUMN id SET DEFAULT nextval('public.document_chunk_id_seq'::regclass);

-- document_chunk document_chunk_pkey; Type: CONSTRAINT; Schema: public; Owner: -
ALTER TABLE ONLY public.document_chunk
    ADD CONSTRAINT document_chunk_pkey PRIMARY KEY (id);

-- document document_pkey; Type: CONSTRAINT; Schema: public; Owner: -
ALTER TABLE ONLY public.document
    ADD CONSTRAINT document_pkey PRIMARY KEY (id);

-- document_chunk document_chunk_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
ALTER TABLE ONLY public.document_chunk
    ADD CONSTRAINT document_chunk_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.document(id) ON DELETE CASCADE;

CREATE INDEX idx_document_chunk_document_id ON public.document_chunk USING btree (document_id);
-- Fresh installations preserve the existing read-only privilege group. Login
-- credentials and role login activation remain externally provisioned.
do $$ begin
    if not exists (select 1 from pg_roles where rolname = 'superset_reader') then
        create role superset_reader nologin nosuperuser nocreatedb nocreaterole
            noreplication nobypassrls;
    end if;
end $$;
grant usage on schema public, analytics to superset_reader;
grant select on all tables in schema public, analytics to superset_reader;
alter default privileges in schema public grant select on tables to superset_reader;
