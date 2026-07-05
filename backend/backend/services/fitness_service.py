from backend.db import get_conn


def recompute_fitness_state(user_id: str) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                with bounds as (
                    select min(date) as min_date, max(date) as max_date
                    from daily_training_load
                    where user_id = %s
                ),
                calendar as (
                    select generate_series(
                        (select min_date from bounds),
                        (select max_date from bounds),
                        interval '1 day'
                    )::date as date
                )
                select
                    c.date,
                    coalesce(d.tss, 0) as daily_tss
                from calendar c
                left join daily_training_load d
                  on d.user_id = %s
                 and d.date = c.date
                order by c.date asc;
                """,
                (user_id, user_id),
            )
            rows = cur.fetchall()

            if not rows:
                cur.execute(
                    """
                    delete from daily_fitness_state
                    where user_id = %s
                      and model_version = 'v1';
                    """,
                    (user_id,),
                )
                conn.commit()

                return {
                    "ok": True,
                    "user_id": user_id,
                    "days_processed": 0,
                    "last_date": None,
                    "last_daily_tss": None,
                    "last_fitness_signal": None,
                    "last_fatigue_signal": None,
                    "last_freshness_signal": None,
                }

    fitness_tau = 42.0
    fatigue_tau = 7.0

    fitness_signal = 0.0
    fatigue_signal = 0.0

    results = []

    for row in rows:
        day, daily_tss = row
        daily_tss = float(daily_tss or 0)

        fitness_signal = fitness_signal + (daily_tss - fitness_signal) / fitness_tau
        fatigue_signal = fatigue_signal + (daily_tss - fatigue_signal) / fatigue_tau
        freshness_signal = fitness_signal - fatigue_signal

        results.append(
            (
                user_id,
                day,
                daily_tss,
                fitness_signal,
                fatigue_signal,
                freshness_signal,
            )
        )

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from daily_fitness_state
                where user_id = %s
                  and model_version = 'v1';
                """,
                (user_id,),
            )

            for item in results:
                cur.execute(
                    """
                    insert into daily_fitness_state (
                        user_id,
                        date,
                        daily_tss,
                        fitness_signal,
                        fatigue_signal,
                        freshness_signal,
                        model_version,
                        computed_at
                    )
                    values (%s, %s, %s, %s, %s, %s, 'v1', now());
                    """,
                    item,
                )

            conn.commit()

    last_day = results[-1]

    return {
        "ok": True,
        "user_id": user_id,
        "days_processed": len(results),
        "last_date": str(last_day[1]),
        "last_daily_tss": last_day[2],
        "last_fitness_signal": last_day[3],
        "last_fatigue_signal": last_day[4],
        "last_freshness_signal": last_day[5],
    }
