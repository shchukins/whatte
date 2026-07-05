import psycopg
from fastapi import HTTPException

from backend.db import get_conn
from backend.services.activity_load_service import resolve_activity_load


def recompute_daily_load_all(user_id: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    m.user_id,
                    date(r.start_date) as day,
                    r.activity_type,
                    m.duration_s,
                    m.distance_m,
                    m.elevation_gain_m,
                    m.work_kj,
                    m.tss,
                    m.normalized_power,
                    m.intensity_factor
                from activity_metrics m
                join strava_activity_raw r
                  on r.strava_activity_id = m.strava_activity_id
                where m.user_id = %s
                  and m.version = 'v1'
                order by day asc;
                """,
                (user_id,),
            )
            rows = cur.fetchall()

            daily_totals: dict[tuple[str, object], dict[str, float | int | object]] = {}

            for row in rows:
                (
                    row_user_id,
                    day,
                    activity_type,
                    duration_s,
                    distance_m,
                    elevation_gain_m,
                    work_kj,
                    tss,
                    normalized_power,
                    intensity_factor,
                ) = row

                load_info = resolve_activity_load(
                    activity_type=activity_type,
                    tss=tss,
                    normalized_power=normalized_power,
                    intensity_factor=intensity_factor,
                )
                if not load_info["load_model_included"]:
                    continue

                key = (row_user_id, day)
                if key not in daily_totals:
                    daily_totals[key] = {
                        "user_id": row_user_id,
                        "day": day,
                        "activities_count": 0,
                        "duration_s": 0.0,
                        "distance_m": 0.0,
                        "elevation_gain_m": 0.0,
                        "work_kj": 0.0,
                        "tss": 0.0,
                    }

                bucket = daily_totals[key]
                bucket["activities_count"] = int(bucket["activities_count"]) + 1
                bucket["duration_s"] = float(bucket["duration_s"]) + float(duration_s or 0)
                bucket["distance_m"] = float(bucket["distance_m"]) + float(distance_m or 0)
                bucket["elevation_gain_m"] = float(bucket["elevation_gain_m"]) + float(elevation_gain_m or 0)
                bucket["work_kj"] = float(bucket["work_kj"]) + float(work_kj or 0)
                bucket["tss"] = float(bucket["tss"]) + float(tss or 0)

            cur.execute(
                """
                delete from daily_training_load
                where user_id = %s;
                """,
                (user_id,),
            )

            aggregated_rows = sorted(
                daily_totals.values(),
                key=lambda item: item["day"],
            )

            for item in aggregated_rows:
                cur.execute(
                    """
                    insert into daily_training_load (
                        user_id,
                        date,
                        activities_count,
                        duration_s,
                        distance_m,
                        elevation_gain_m,
                        work_kj,
                        tss,
                        computed_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, now())
                    on conflict (user_id, date) do update set
                        activities_count = excluded.activities_count,
                        duration_s = excluded.duration_s,
                        distance_m = excluded.distance_m,
                        elevation_gain_m = excluded.elevation_gain_m,
                        work_kj = excluded.work_kj,
                        tss = excluded.tss,
                        computed_at = now();
                    """,
                    (
                        item["user_id"],
                        item["day"],
                        item["activities_count"],
                        item["duration_s"],
                        item["distance_m"],
                        item["elevation_gain_m"],
                        item["work_kj"],
                        item["tss"],
                    ),
                )

            conn.commit()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"no activity_metrics found for user_id={user_id}",
        )

    if not aggregated_rows:
        return {
            "ok": True,
            "user_id": user_id,
            "days_processed": 0,
            "from_date": None,
            "to_date": None,
        }

    return {
        "ok": True,
        "user_id": user_id,
        "days_processed": len(aggregated_rows),
        "from_date": str(aggregated_rows[0]["day"]),
        "to_date": str(aggregated_rows[-1]["day"]),
    }
