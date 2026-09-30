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
