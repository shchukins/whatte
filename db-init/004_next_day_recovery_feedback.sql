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
