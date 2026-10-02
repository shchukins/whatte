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
