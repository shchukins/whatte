"""Dated user inputs; manual weight is not a physiology/recovery observation."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.config import settings
from backend.db import get_conn


def local_today() -> date:
    return datetime.now(ZoneInfo(settings.whatte_timezone)).date()


class ProfileChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    metric: Literal['ftp', 'hr_max', 'weight']
    effective_from: date
    value: float = Field(gt=0, le=1000, allow_inf_nan=False)

    @model_validator(mode='after')
    def validate_input(self):
        # Broad input sanity limits, not physiological scoring thresholds.
        if self.value < 1 or (self.metric == 'weight' and self.value > 500):
            raise ValueError('Value is outside the supported range')
        if self.metric == 'hr_max' and (self.value > 250 or not self.value.is_integer()):
            raise ValueError('HR max must be a whole number between 1 and 250')
        if self.effective_from > local_today():
            raise ValueError('Future effective dates are not supported')
        return self


@contextmanager
def _profile_lock(user_id: str):
    # Session lock survives commits made by the existing recompute services.
    # A second form submission fails promptly instead of waiting on a long run.
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('select pg_try_advisory_lock(hashtextextended(%s, 0))',
                        ('user-profile:' + user_id,))
            if not cur.fetchone()[0]:
                raise HTTPException(409, 'Profile update is already in progress')
        try:
            yield conn
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute('select pg_advisory_unlock(hashtextextended(%s, 0))',
                            ('user-profile:' + user_id,))


def get_profile(user_id: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''select metric, effective_from, value, needs_recompute
                           from user_profile_value where user_id = %s
                           order by effective_from desc, metric''', (user_id,))
            rows = cur.fetchall()
    history = [dict(metric=m, effective_from=d, value=float(v), pending=p)
               for m, d, v, p in rows]
    current = {}
    for row in history:
        if row['effective_from'] <= local_today():
            current.setdefault(row['metric'], row)
    pending = [r['effective_from'] for r in history if r['pending']]
    return dict(history=history, current=current,
                pending_from=min(pending) if pending else None, today=local_today())


def save_profile_value(user_id: str, change: ProfileChange) -> None:
    with _profile_lock(user_id) as conn:
        with conn.cursor() as cur:
            cur.execute('''
                insert into user_profile_value
                    (user_id, metric, effective_from, value, needs_recompute)
                values (%s, %s, %s, %s, %s)
                on conflict (user_id, metric, effective_from) do update set
                    value = excluded.value,
                    needs_recompute = user_profile_value.needs_recompute or
                        (excluded.metric in ('ftp', 'hr_max') and
                         user_profile_value.value <> excluded.value),
                    updated_at = now()
            ''', (user_id, change.metric, change.effective_from, change.value,
                  change.metric in ('ftp', 'hr_max')))
        conn.commit()


def resolve_activity_profile(cur, user_id: str, activity_id: int) -> tuple:
    """Use the latest input on/before the activity's local calendar date.

    FTP and HR max edits do not infer power or HR zone changes. Legacy zone
    boundaries remain independent and are selected with the same effective-date cutoff.
    Missing inputs stay unavailable; future profiles never leak into history.
    """
    cur.execute('''
        with activity as (
            select (start_date at time zone %s)::date as day
            from strava_activity_raw where user_id = %s and strava_activity_id = %s
        )
        select coalesce(v.value, p.ftp_watts), coalesce(h.value, p.hr_max),
               p.power_z1_upper, p.power_z2_upper, p.power_z3_upper,
               p.power_z4_upper, p.power_z5_upper, p.power_z6_upper,
               p.hr_z1_upper, p.hr_z2_upper, p.hr_z3_upper, p.hr_z4_upper
        from activity a
        left join lateral (
            select * from user_training_profile where user_id = %s
              and effective_from <= a.day order by effective_from desc limit 1
        ) p on true
        left join lateral (
            select value from user_profile_value where user_id = %s
              and metric = 'ftp' and effective_from <= a.day
            order by effective_from desc limit 1
        ) v on true
        left join lateral (
            select value from user_profile_value where user_id = %s
              and metric = 'hr_max' and effective_from <= a.day
            order by effective_from desc limit 1
        ) h on true
    ''', (settings.whatte_timezone, user_id, activity_id, user_id, user_id, user_id))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(404, 'Activity not found')
    return tuple(float(v) if v is not None else None for v in row)


def recompute_profile_history(user_id: str) -> int:
    # Only stored inputs are read: no Strava fetch and no notification delivery.
    from backend.services.pipeline_service import compute_and_store_activity_metrics
    from backend.services.activity_response_service import compute_and_store_activity_response
    from backend.services.activity_deduplication_service import recompute_after_activity_state_change

    with _profile_lock(user_id) as conn:
        with conn.cursor() as cur:
            cur.execute('''select min(effective_from) from user_profile_value
                           where user_id = %s and needs_recompute''', (user_id,))
            from_date = cur.fetchone()[0]
            if from_date is None:
                return 0
            cur.execute('''
                select r.strava_activity_id,
                       not r.is_excluded and r.duplicate_of_activity_id is null
                from strava_activity_raw r
                join activity_metrics m on m.strava_activity_id = r.strava_activity_id
                    and m.version = 'v1'
                where r.user_id = %s and not r.is_deleted
                  and (r.start_date at time zone %s)::date >= %s
                order by r.start_date, r.strava_activity_id
            ''', (user_id, settings.whatte_timezone, from_date))
            activities = cur.fetchall()
            ids = [r[0] for r in activities]
            response_ids = [r[0] for r in activities if r[1]]
        for activity_id in ids:
            compute_and_store_activity_metrics(activity_id)
        # Chronological response rebuild also refreshes later comparable baselines.
        for activity_id in response_ids:
            compute_and_store_activity_response(activity_id)
        if ids:
            # Existing daily aggregates use UTC days; include the preceding day
            # for activities falling across the profile's local-date boundary.
            recompute_after_activity_state_change(
                user_id, from_date - timedelta(days=1), through_date=str(local_today())
            )
        with conn.cursor() as cur:
            cur.execute('''update user_profile_value set needs_recompute = false
                           where user_id = %s and needs_recompute''', (user_id,))
        conn.commit()
    return len(ids)
