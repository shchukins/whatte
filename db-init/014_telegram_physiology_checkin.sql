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
