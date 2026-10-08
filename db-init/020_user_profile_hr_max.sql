-- Extend the independent dated profile; never derive zones from HR max.
begin;

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

commit;
