from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.db import get_conn
from backend.services.decision_engine import build_readiness_briefing, build_recommendation


def get_readiness_daily_for_date(user_id: str, target_date: str) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    user_id,
                    date,
                    readiness_score,
                    good_day_probability,
                    status_text,
                    explanation_json
                from readiness_daily
                where user_id = %s
                  and date = %s
                  and version = 'v2';
                """,
                (user_id, target_date),
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"readiness not found for user_id={user_id} date={target_date}",
                )

            db_user_id, db_date, readiness_score, good_day_probability, status_text, explanation_json = row

    decision = build_recommendation(
        readiness_score=readiness_score,
        explanation=explanation_json,
    )
    briefing = build_readiness_briefing(
        readiness_score=readiness_score,
        status_text=status_text,
        recommendation=decision["recommendation"],
        reason=decision["reason"],
        explanation=explanation_json,
    )

    return {
        "ok": True,
        "user_id": db_user_id,
        "date": str(db_date),
        "readiness_score": readiness_score,
        "good_day_probability": good_day_probability,
        "status_text": status_text,
        "explanation": explanation_json,
        **decision,
        **briefing,
        "briefing_text": briefing["briefing"],
    }


def get_readiness_daily_history(user_id: str, days: int) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    date,
                    readiness_score,
                    good_day_probability,
                    status_text,
                    explanation_json
                from readiness_daily
                where user_id = %s
                  and version = 'v2'
                order by date desc
                limit %s;
                """,
                (user_id, days),
            )
            rows = cur.fetchall()

    points = [
        {
            "date": str(row_date),
            "readiness_score": readiness_score,
            "good_day_probability": good_day_probability,
            "status_text": status_text,
            "explanation": explanation_json,
        }
        for row_date, readiness_score, good_day_probability, status_text, explanation_json in rows
    ]
    points.reverse()

    return {
        "ok": True,
        "user_id": user_id,
        "days": days,
        "points": points,
    }
