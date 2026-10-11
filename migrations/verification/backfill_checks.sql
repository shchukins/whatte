-- Aggregate violations only. Existing manual corrections are valid; do not
-- compare their values to legacy inputs or mutate them during baseline adoption.
SELECT jsonb_build_object(
    'canonical_feedback_missing', (select count(*) from activity_subjective_feedback
        where canonical_activity_id is null and strava_activity_id is not null),
    'legacy_ftp_missing', (select count(*) from user_training_profile p
        where p.ftp_watts between 1 and 1000 and not exists (select 1 from user_profile_value v
            where v.user_id = p.user_id and v.metric = 'ftp' and v.effective_from = p.effective_from)),
    'legacy_hr_max_missing', (select count(*) from user_training_profile p
        where p.hr_max between 1 and 250 and not exists (select 1 from user_profile_value v
            where v.user_id = p.user_id and v.metric = 'hr_max' and v.effective_from = p.effective_from)),
    'daily_delivery_state_missing', (select count(*) from notification_log
        where notification_type = 'daily_readiness' and (freshness_status is null or delivery_status is null))
);
