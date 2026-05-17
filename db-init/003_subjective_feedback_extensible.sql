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
