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
