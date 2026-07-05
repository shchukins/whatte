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
