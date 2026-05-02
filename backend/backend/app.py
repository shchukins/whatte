from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any

import psycopg
import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from backend.config import settings
from backend.core.logging import configure_logging, log_event
from backend.db import get_conn
from backend.services.fitness_service import recompute_fitness_state
from backend.services.ingest_service import process_one_strava_ingest_job
from backend.services.load_service import recompute_daily_load_all
from backend.services.metrics_service import (
    compute_deltas,
    compute_hr_zones,
    compute_power_metrics,
    compute_power_zones,
    rolling_mean,
)
from backend.services.notification_service import send_daily_readiness
from backend.services.pipeline_service import process_activity_pipeline
from backend.services.strava_auth import refresh_strava_token_if_needed
from backend.services.strava_client import (
    fetch_activity,
    fetch_activity_streams,
    list_activities,
)
from backend.schemas.healthkit import HealthIngestResponse, HealthSyncPayload
from backend.services.healthkit_ingest import save_healthkit_ingest_raw
from backend.services.healthkit_processing import process_latest_healthkit_raw
from backend.services.health_recovery_daily import recompute_health_recovery_daily_for_date
from backend.services.load_state_v2 import recompute_load_state_daily_v2
from backend.services.readiness_daily import recompute_readiness_daily_for_date
from backend.services.healthkit_pipeline import ingest_and_process_healthkit_payload
from backend.services.readiness_query import (
    get_readiness_daily_for_date,
    get_readiness_daily_history,
)
from backend.services.decision_engine import build_readiness_briefing

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Human Engine API", version="0.1.0")


class EventIn(BaseModel):
    source: str = Field(min_length=1, examples=["strava", "healthkit"])
    event_type: str = Field(min_length=1, examples=["webhook", "sleep_sync"])
    payload: dict[str, Any]


class EventOut(BaseModel):
    id: int
    source: str
    event_type: str
    payload: dict[str, Any]
    received_at: datetime


class StravaWebhookChallengeResponse(BaseModel):
    hub_challenge: str = Field(alias="hub.challenge")


class AIRideBriefingRequest(BaseModel):
    readiness: str
    readiness_score: float | None = None
    status_text: str | None = None
    recommendation: str | None = None
    reason: str | None = None
    explanation: dict[str, Any] | None = None
    readiness_context: str | None = None
    weather_summary: str | None = None
    training_suggestion: str | None = None
    checklist: list[str] | None = None
    extra_notes: str | None = None


class AIRideBriefingData(BaseModel):
    title: str
    summary: str
    readiness_score: float | None = None
    status_text: str | None = None
    briefing: str | None = None
    recommendation: str | None = None
    reason: str | None = None
    weather_note: str
    training_note: str
    checklist: list[str]
    extra_note: str


class AIRideBriefingResponse(BaseModel):
    model: str
    data: AIRideBriefingData


def _get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return request_id

    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    return request_id


def _extract_user_id(request: Request) -> str | None:
    path_user_id = request.path_params.get("user_id")
    if path_user_id:
        return str(path_user_id)

    header_user_id = request.headers.get("x-user-id")
    if header_user_id:
        return header_user_id

    return None


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    started_at = time.perf_counter()
    request_id = _get_request_id(request)
    user_id = _extract_user_id(request)
    request.state.user_id = user_id

    log_event(
        logger,
        "api_request_started",
        method=request.method,
        path=request.url.path,
        request_id=request_id,
        user_id=user_id,
    )

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        log_event(
            logger,
            "error",
            level=logging.ERROR,
            error_type=type(exc).__name__,
            error=str(exc),
            context="request_exception",
            method=request.method,
            path=request.url.path,
            request_id=request_id,
            user_id=_extract_user_id(request),
            duration_ms=duration_ms,
        )
        raise

    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    user_id = _extract_user_id(request)
    request.state.user_id = user_id
    response.headers["X-Request-ID"] = request_id

    log_event(
        logger,
        "api_request_finished",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
        request_id=request_id,
        user_id=user_id,
    )

    if response.status_code >= 400:
        log_event(
            logger,
            "error",
            level=logging.ERROR,
            error_type="HTTPError",
            error=f"request failed with status {response.status_code}",
            context="http_response",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            request_id=request_id,
            user_id=user_id,
        )

    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": f"internal server error: {type(exc).__name__}"},
        headers={"X-Request-ID": _get_request_id(request)},
    )


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/dbz")
def dbz():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return {"db": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"db error: {exc}")


def translate_checklist_items(items: list[str] | None) -> list[str]:
    if not items:
        return []

    dictionary = {
        "helmet": "Шлем",
        "water bottle": "Бутылка с водой",
        "mini pump": "Мини-насос",
        "rear light": "Задний фонарь",
        "front light": "Передний фонарь",
        "gloves": "Перчатки",
        "tool kit": "Набор инструментов",
        "rain jacket": "Дождевик",
    }

    result: list[str] = []
    for item in items:
        translated = dictionary.get(item.strip().lower(), item)
        result.append(translated)
    return result


def localize_weather_summary(text: str | None) -> str:
    if not text:
        return "Нет данных о погоде."

    result = text.strip()

    replacements = {
        "Dry": "Сухо",
        "dry": "сухо",
        "light wind": "легкий ветер",
        "Light wind": "Легкий ветер",
        "wind": "ветер",
    }

    for src, dst in replacements.items():
        result = result.replace(src, dst)

    return result


def localize_training_suggestion(text: str | None) -> str:
    if not text:
        return "Нет данных о тренировке."

    result = text.strip()

    replacements = {
        "Endurance ride": "Поездка на выносливость",
        "endurance ride": "поездка на выносливость",
        "Recovery ride": "Восстановительная поездка",
        "recovery ride": "восстановительная поездка",
        "Tempo ride": "Темповая поездка",
        "tempo ride": "темповая поездка",
        "minutes": "минут",
        "minute": "минута",
    }

    for src, dst in replacements.items():
        result = result.replace(src, dst)

    return result


def localize_extra_notes(text: str | None) -> str:
    if not text:
        return ""

    result = text.strip()

    if result.startswith("Sunset at "):
        time_part = result.removeprefix("Sunset at ").strip()
        return f"Закат в {time_part}."

    return result


def build_ride_briefing_data(payload: AIRideBriefingRequest) -> AIRideBriefingData:
    checklist = translate_checklist_items(payload.checklist)

    localized_weather = localize_weather_summary(payload.weather_summary)
    localized_training = localize_training_suggestion(payload.training_suggestion)
    localized_extra = localize_extra_notes(payload.extra_notes)

    readiness_text = f"Готовность: {payload.readiness}."
    weather_text = f"Погода: {localized_weather}."
    training_text = f"Тренировка: {localized_training}."

    briefing: dict[str, str] | None = None
    if payload.readiness_score is not None or payload.recommendation is not None:
        briefing = build_readiness_briefing(
            readiness_score=payload.readiness_score,
            status_text=payload.status_text or payload.readiness,
            recommendation=payload.recommendation,
            reason=payload.reason,
            explanation=payload.explanation,
        )

    summary = briefing["briefing"] if briefing else f"{readiness_text} {weather_text} {training_text}"

    return AIRideBriefingData(
        title="Брифинг перед поездкой",
        summary=summary,
        readiness_score=payload.readiness_score,
        status_text=payload.status_text or payload.readiness,
        briefing=briefing["briefing"] if briefing else summary,
        recommendation=briefing["recommendation"] if briefing else payload.recommendation,
        reason=briefing["reason"] if briefing else payload.reason,
        weather_note=localized_weather,
        training_note=localized_training,
        checklist=checklist,
        extra_note=localized_extra,
    )


@app.post("/ai/ride-briefing-json", response_model=AIRideBriefingResponse)
async def ai_ride_briefing(payload: AIRideBriefingRequest):
    data = build_ride_briefing_data(payload)
    return AIRideBriefingResponse(
        model="deterministic",
        data=data,
    )


@app.get("/events", response_model=list[EventOut])
def list_events(limit: int = Query(default=20, ge=1, le=200)):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, source, event_type, payload, received_at
                    FROM events
                    ORDER BY received_at DESC
                    LIMIT %s;
                    """,
                    (limit,),
                )
                rows = cur.fetchall()

        return [
            {
                "id": r[0],
                "source": r[1],
                "event_type": r[2],
                "payload": r[3],
                "received_at": r[4],
            }
            for r in rows
        ]
    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"db error: {e}")
    
    
@app.get("/strava/webhook", response_model=StravaWebhookChallengeResponse)
def strava_webhook_verify(
    hub_mode: str = Query(alias="hub.mode"),
    hub_challenge: str = Query(alias="hub.challenge"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
):
    # Strava ожидает JSON: {"hub.challenge": "<value>"}
    if hub_verify_token != settings.strava_verify_token:
        raise HTTPException(status_code=401, detail="invalid verify token")
    return {"hub.challenge": hub_challenge}


@app.post("/strava/webhook")
async def strava_webhook_receive(request: Request):
    payload = await request.json()

    aspect_type = payload.get("aspect_type", "webhook")
    object_type = payload.get("object_type")
    object_id = payload.get("object_id")
    owner_id = payload.get("owner_id")
    subscription_id = payload.get("subscription_id")
    updates = payload.get("updates")
    event_time_unix = payload.get("event_time")

    if not object_type or object_id is None or owner_id is None or event_time_unix is None:
        raise HTTPException(status_code=400, detail="invalid strava webhook payload")

    log_event(
        logger,
        "strava_webhook_received",
        request_id=_get_request_id(request),
        owner_id=owner_id,
        object_id=object_id,
        object_type=object_type,
        aspect_type=aspect_type,
        subscription_id=subscription_id,
    )

    dedupe_key = (
        f"strava:{subscription_id}:{owner_id}:"
        f"{object_type}:{object_id}:{aspect_type}:{event_time_unix}"
    )

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into strava_webhook_event (
                        subscription_id,
                        owner_id,
                        object_type,
                        object_id,
                        aspect_type,
                        event_time,
                        updates,
                        payload,
                        dedupe_key
                    )
                    values (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        to_timestamp(%s),
                        %s::jsonb,
                        %s::jsonb,
                        %s
                    )
                    on conflict (dedupe_key) do nothing
                    returning id;
                    """,
                    (
                        subscription_id,
                        owner_id,
                        object_type,
                        object_id,
                        aspect_type,
                        event_time_unix,
                        json.dumps(updates) if updates is not None else None,
                        json.dumps(payload),
                        dedupe_key,
                    ),
                )
                webhook_row = cur.fetchone()
                webhook_event_id = webhook_row[0] if webhook_row else None

                if (
                    webhook_event_id is not None
                    and object_type == "activity"
                    and aspect_type in ("create", "update")
                ):
                    cur.execute(
                        """
                        select user_id
                        from user_strava_connection
                        where strava_athlete_id = %s;
                        """,
                        (owner_id,),
                    )
                    user_row = cur.fetchone()

                    if user_row:
                        user_id = user_row[0]
                        cur.execute(
                            """
                            insert into strava_activity_ingest_job (
                                webhook_event_id,
                                user_id,
                                strava_athlete_id,
                                strava_activity_id,
                                reason,
                                status
                            )
                            values (%s, %s, %s, %s, %s, 'pending')
                            on conflict do nothing
                            returning id;
                            """,
                            (
                                webhook_event_id,
                                user_id,
                                owner_id,
                                object_id,
                                f"webhook_{aspect_type}",
                            ),
                        )
                        job_row = cur.fetchone()
                        job_id = job_row[0] if job_row else None

                        if job_id is not None:
                            log_event(
                                logger,
                                "strava_ingest_job_created",
                                request_id=_get_request_id(request),
                                user_id=user_id,
                                job_id=job_id,
                                owner_id=owner_id,
                                activity_id=object_id,
                                aspect_type=aspect_type,
                                webhook_event_id=webhook_event_id,
                            )

                conn.commit()

        return {"ok": True, "event_id": webhook_event_id}
    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"db error: {e}")



@app.post("/debug/strava/fetch-one")
def debug_strava_fetch_one():
    try:
        return process_one_strava_ingest_job()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"http error: {e}")
    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"db error: {e}")


@app.post("/debug/strava/fetch-streams/{activity_id}")
def debug_strava_fetch_streams(activity_id: int):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select user_id, strava_athlete_id
                    from strava_activity_raw
                    where strava_activity_id = %s;
                    """,
                    (activity_id,),
                )
                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"activity not found in strava_activity_raw: {activity_id}",
                    )

                user_id, athlete_id = row

        access_token, _, _ = refresh_strava_token_if_needed(user_id)

        streams = fetch_activity_streams(
            access_token=access_token,
            activity_id=activity_id,
        )

        saved = 0

        with get_conn() as conn:
            with conn.cursor() as cur:
                for stream_type, stream_payload in streams.items():
                    cur.execute(
                        """
                        insert into strava_activity_stream_raw (
                            strava_activity_id,
                            stream_type,
                            series_type,
                            resolution,
                            original_size,
                            data_json,
                            fetched_at
                        )
                        values (%s, %s, %s, %s, %s, %s::jsonb, now())
                        on conflict (strava_activity_id, stream_type) do update set
                            series_type = excluded.series_type,
                            resolution = excluded.resolution,
                            original_size = excluded.original_size,
                            data_json = excluded.data_json,
                            fetched_at = now();
                        """,
                        (
                            activity_id,
                            stream_type,
                            stream_payload.get("series_type"),
                            stream_payload.get("resolution"),
                            stream_payload.get("original_size"),
                            json.dumps(stream_payload),
                        ),
                    )
                    saved += 1

                conn.commit()

        return {
            "ok": True,
            "activity_id": activity_id,
            "user_id": user_id,
            "streams_saved": saved,
            "stream_types": list(streams.keys()),
        }

    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"http error: {e}")
    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"db error: {e}")

@app.post("/debug/metrics/compute/{activity_id}")
def debug_compute_activity_metrics(activity_id: int):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        user_id,
                        strava_activity_id,
                        moving_time_s,
                        elapsed_time_s,
                        distance_m,
                        total_elevation_gain_m,
                        average_speed_mps,
                        max_speed_mps,
                        average_heartrate,
                        max_heartrate,
                        average_watts,
                        max_watts,
                        weighted_average_watts,
                        kilojoules
                    from strava_activity_raw
                    where strava_activity_id = %s;
                    """,
                    (activity_id,),
                )
                raw_row = cur.fetchone()

                if not raw_row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"activity not found in strava_activity_raw: {activity_id}",
                    )

                (
                    user_id,
                    strava_activity_id,
                    moving_time_s,
                    elapsed_time_s,
                    distance_m,
                    elevation_gain_m,
                    avg_speed_mps,
                    max_speed_mps,
                    avg_heartrate,
                    max_heartrate,
                    avg_power,
                    max_power,
                    weighted_avg_power,
                    work_kj,
                ) = raw_row

                cur.execute(
                    """
                    select
                        ftp_watts,
                        hr_max,
                        power_z1_upper,
                        power_z2_upper,
                        power_z3_upper,
                        power_z4_upper,
                        power_z5_upper,
                        power_z6_upper,
                        hr_z1_upper,
                        hr_z2_upper,
                        hr_z3_upper,
                        hr_z4_upper
                    from user_training_profile
                    where user_id = %s
                    order by effective_from desc
                    limit 1;
                    """,
                    (user_id,),
                )
                profile_row = cur.fetchone()

                if not profile_row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"user_training_profile not found for user_id={user_id}",
                    )

                (
                    ftp_watts,
                    hr_max,
                    power_z1_upper,
                    power_z2_upper,
                    power_z3_upper,
                    power_z4_upper,
                    power_z5_upper,
                    power_z6_upper,
                    hr_z1_upper,
                    hr_z2_upper,
                    hr_z3_upper,
                    hr_z4_upper,
                ) = profile_row

                cur.execute(
                    """
                    select stream_type, data_json
                    from strava_activity_stream_raw
                    where strava_activity_id = %s;
                    """,
                    (activity_id,),
                )
                stream_rows = cur.fetchall()

        streams = {}
        for stream_type, data_json in stream_rows:
            streams[stream_type] = data_json

        time_stream = streams.get("time", {}).get("data", [])
        watts_stream = streams.get("watts", {}).get("data", [])
        hr_stream = streams.get("heartrate", {}).get("data", [])

        if not time_stream:
            raise HTTPException(
                status_code=400,
                detail=f"time stream not found for activity_id={activity_id}",
            )


        deltas = compute_deltas(time_stream)

        power_metrics = compute_power_metrics(
            watts_stream=watts_stream,
            avg_power=avg_power,
            ftp_watts=ftp_watts,
            elapsed_time_s=elapsed_time_s,
        )

        normalized_power = power_metrics["normalized_power"]
        intensity_factor = power_metrics["intensity_factor"]
        variability_index = power_metrics["variability_index"]
        tss = power_metrics["tss"]

        if watts_stream and ftp_watts and ftp_watts > 0:
            watts_values = [float(v) if v is not None else 0.0 for v in watts_stream]
            rolling_30s = rolling_mean(watts_values, 30)

            if rolling_30s:
                fourth_power_mean = sum(v ** 4 for v in rolling_30s) / len(rolling_30s)
                normalized_power = fourth_power_mean ** 0.25

                if avg_power and avg_power > 0:
                    variability_index = normalized_power / avg_power

                intensity_factor = normalized_power / ftp_watts

                if elapsed_time_s and elapsed_time_s > 0:
                    tss = (elapsed_time_s * normalized_power * intensity_factor) / (ftp_watts * 3600) * 100

        power_zones = {
            "z1": 0,
            "z2": 0,
            "z3": 0,
            "z4": 0,
            "z5": 0,
            "z6": 0,
            "z7": 0,
        }

        power_zones = compute_power_zones(
            watts_stream=watts_stream,
            deltas=deltas,
            power_z1_upper=power_z1_upper,
            power_z2_upper=power_z2_upper,
            power_z3_upper=power_z3_upper,
            power_z4_upper=power_z4_upper,
            power_z5_upper=power_z5_upper,
            power_z6_upper=power_z6_upper,
        )

        hr_zones = compute_hr_zones(
            hr_stream=hr_stream,
            deltas=deltas,
            hr_z1_upper=hr_z1_upper,
            hr_z2_upper=hr_z2_upper,
            hr_z3_upper=hr_z3_upper,
            hr_z4_upper=hr_z4_upper,
        )

        metrics_json = {
            "source": "debug_metrics_v1",
            "streams_present": list(streams.keys()),
            "ftp_watts": ftp_watts,
            "hr_max": hr_max,
        }

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into activity_metrics (
                        user_id,
                        strava_activity_id,
                        version,
                        duration_s,
                        moving_time_s,
                        distance_m,
                        elevation_gain_m,
                        avg_speed_mps,
                        max_speed_mps,
                        avg_heartrate,
                        max_heartrate,
                        avg_power,
                        max_power,
                        weighted_avg_power,
                        normalized_power,
                        intensity_factor,
                        variability_index,
                        work_kj,
                        tss,
                        time_in_power_z1_s,
                        time_in_power_z2_s,
                        time_in_power_z3_s,
                        time_in_power_z4_s,
                        time_in_power_z5_s,
                        time_in_power_z6_s,
                        time_in_power_z7_s,
                        time_in_hr_z1_s,
                        time_in_hr_z2_s,
                        time_in_hr_z3_s,
                        time_in_hr_z4_s,
                        time_in_hr_z5_s,
                        raw_json,
                        computed_at
                    )
                    values (
                        %s, %s, 'v1', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s::jsonb, now()
                    )
                    on conflict (strava_activity_id, version) do update set
                        user_id = excluded.user_id,
                        duration_s = excluded.duration_s,
                        moving_time_s = excluded.moving_time_s,
                        distance_m = excluded.distance_m,
                        elevation_gain_m = excluded.elevation_gain_m,
                        avg_speed_mps = excluded.avg_speed_mps,
                        max_speed_mps = excluded.max_speed_mps,
                        avg_heartrate = excluded.avg_heartrate,
                        max_heartrate = excluded.max_heartrate,
                        avg_power = excluded.avg_power,
                        max_power = excluded.max_power,
                        weighted_avg_power = excluded.weighted_avg_power,
                        normalized_power = excluded.normalized_power,
                        intensity_factor = excluded.intensity_factor,
                        variability_index = excluded.variability_index,
                        work_kj = excluded.work_kj,
                        tss = excluded.tss,
                        time_in_power_z1_s = excluded.time_in_power_z1_s,
                        time_in_power_z2_s = excluded.time_in_power_z2_s,
                        time_in_power_z3_s = excluded.time_in_power_z3_s,
                        time_in_power_z4_s = excluded.time_in_power_z4_s,
                        time_in_power_z5_s = excluded.time_in_power_z5_s,
                        time_in_power_z6_s = excluded.time_in_power_z6_s,
                        time_in_power_z7_s = excluded.time_in_power_z7_s,
                        time_in_hr_z1_s = excluded.time_in_hr_z1_s,
                        time_in_hr_z2_s = excluded.time_in_hr_z2_s,
                        time_in_hr_z3_s = excluded.time_in_hr_z3_s,
                        time_in_hr_z4_s = excluded.time_in_hr_z4_s,
                        time_in_hr_z5_s = excluded.time_in_hr_z5_s,
                        raw_json = excluded.raw_json,
                        computed_at = now();
                    """,
                    (
                        user_id,
                        strava_activity_id,
                        elapsed_time_s,
                        moving_time_s,
                        distance_m,
                        elevation_gain_m,
                        avg_speed_mps,
                        max_speed_mps,
                        avg_heartrate,
                        max_heartrate,
                        avg_power,
                        max_power,
                        weighted_avg_power,
                        normalized_power,
                        intensity_factor,
                        variability_index,
                        work_kj,
                        tss,
                        power_zones["z1"],
                        power_zones["z2"],
                        power_zones["z3"],
                        power_zones["z4"],
                        power_zones["z5"],
                        power_zones["z6"],
                        power_zones["z7"],
                        hr_zones["z1"],
                        hr_zones["z2"],
                        hr_zones["z3"],
                        hr_zones["z4"],
                        hr_zones["z5"],
                        json.dumps(metrics_json),
                    ),
                )
                conn.commit()

        return {
            "ok": True,
            "activity_id": activity_id,
            "user_id": user_id,
            "normalized_power": normalized_power,
            "intensity_factor": intensity_factor,
            "variability_index": variability_index,
            "tss": tss,
            "power_zones_s": power_zones,
            "hr_zones_s": hr_zones,
        }

    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"db error: {e}")

@app.post("/debug/load/compute-day/{user_id}/{date_str}")
def debug_compute_daily_load(user_id: str, date_str: str):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    select
                        count(*),
                        coalesce(sum(duration_s),0),
                        coalesce(sum(distance_m),0),
                        coalesce(sum(elevation_gain_m),0),
                        coalesce(sum(work_kj),0),
                        coalesce(sum(tss),0)
                    from activity_metrics
                    where user_id = %s
                      and date(computed_at) = %s::date;
                    """,
                    (user_id, date_str),
                )

                row = cur.fetchone()

                (
                    activities_count,
                    duration_s,
                    distance_m,
                    elevation_gain_m,
                    work_kj,
                    tss,
                ) = row

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
                    values (%s,%s,%s,%s,%s,%s,%s,%s,now())
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
                        user_id,
                        date_str,
                        activities_count,
                        duration_s,
                        distance_m,
                        elevation_gain_m,
                        work_kj,
                        tss,
                    ),
                )

                conn.commit()

        return {
            "ok": True,
            "user_id": user_id,
            "date": date_str,
            "activities": activities_count,
            "tss": tss,
        }

    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"db error: {e}")


@app.post("/debug/fitness/recompute/{user_id}")
def debug_recompute_fitness_state(user_id: str):
    try:
        return recompute_fitness_state(user_id)
    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"db error: {e}")


@app.get("/debug/strava/list-activities/{user_id}")
def debug_list_strava_activities(user_id: str, per_page: int = 30, page: int = 1):
    try:
        access_token, _, _ = refresh_strava_token_if_needed(user_id)

        activities = list_activities(
            access_token=access_token,
            per_page=per_page,
            page=page,
        )

        result = []
        for item in activities:
            result.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "sport_type": item.get("sport_type") or item.get("type"),
                    "start_date": item.get("start_date"),
                    "distance": item.get("distance"),
                    "moving_time": item.get("moving_time"),
                }
            )

        return {
            "ok": True,
            "user_id": user_id,
            "page": page,
            "per_page": per_page,
            "count": len(result),
            "activities": result,
        }

    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"http error: {e}")



@app.post("/debug/backfill/recent/{user_id}")
def debug_backfill_recent(user_id: str, per_page: int = 5, page: int = 1):
    try:
        access_token, _, _ = refresh_strava_token_if_needed(user_id)

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select strava_athlete_id
                    from user_strava_connection
                    where user_id = %s;
                    """,
                    (user_id,),
                )
                athlete_row = cur.fetchone()

                if not athlete_row:
                    raise HTTPException(
                        status_code=404,
                        detail=f"user_strava_connection not found for user_id={user_id}",
                    )

                athlete_id = athlete_row[0]

        activities = list_activities(
            access_token=access_token,
            per_page=per_page,
            page=page,
        )

        results = []

        for a in activities:
            activity_id = a.get("id")

            try:
                result = process_activity_pipeline(
                    user_id=user_id,
                    athlete_id=athlete_id,
                    activity_id=activity_id,
                )

                results.append(
                    {
                        "activity_id": activity_id,
                        "name": a.get("name"),
                        "status": "ok",
                        "tss": result.get("tss"),
                    }
                )

            except Exception as e:
                results.append(
                    {
                        "activity_id": activity_id,
                        "name": a.get("name"),
                        "status": "failed",
                        "error": str(e)[:200],
                    }
                )

        return {
            "ok": True,
            "user_id": user_id,
            "count": len(results),
            "results": results,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/debug/load/recompute-all/{user_id}")
def debug_recompute_daily_load_all(user_id: str):
    try:
        return recompute_daily_load_all(user_id)
    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"db error: {e}")



@app.get("/fitness/history/{user_id}")
def fitness_history(user_id: str, limit: int = 120):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                        date,
                        daily_tss,
                        fitness_signal,
                        fatigue_signal,
                        freshness_signal
                    from daily_fitness_state
                    where user_id = %s
                    order by date desc
                    limit %s;
                    """,
                    (user_id, limit),
                )

                rows = cur.fetchall()

        result = []
        for r in rows:
            result.append(
                {
                    "date": str(r[0]),
                    "tss": float(r[1]),
                    "fitness": float(r[2]),
                    "fatigue": float(r[3]),
                    "freshness": float(r[4]),
                }
            )

        result.reverse()

        return {
            "ok": True,
            "user_id": user_id,
            "points": len(result),
            "data": result,
        }

    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"db error: {e}")

@app.get("/strava/connect")
def strava_connect(user_id: str):
    scope = "activity:read_all"

    authorize_url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={settings.strava_client_id}"
        f"&response_type=code"
        f"&redirect_uri={settings.strava_redirect_uri}"
        f"&approval_prompt=force"
        f"&scope={scope}"
        f"&state={user_id}"
    )

    return RedirectResponse(authorize_url)


@app.get("/strava/callback")
def strava_callback(
    code: str | None = None,
    scope: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        raise HTTPException(status_code=400, detail=f"strava auth error: {error}")

    if not code:
        raise HTTPException(status_code=400, detail="missing authorization code")

    if not state:
        raise HTTPException(status_code=400, detail="missing state/user_id")

    accepted_scopes = set((scope or "").split(","))

    if "activity:read_all" not in accepted_scopes:
        raise HTTPException(
            status_code=400,
            detail=f"required scope not granted: activity:read_all; got={scope}",
        )

    response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": settings.strava_client_id,
            "client_secret": settings.strava_client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"strava token exchange failed {response.status_code}: {response.text[:300]}",
        )

    payload = response.json()

    athlete = payload.get("athlete") or {}
    strava_athlete_id = athlete.get("id")

    if not strava_athlete_id:
        raise HTTPException(status_code=502, detail="missing athlete id in token exchange response")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into user_strava_connection (
                    user_id,
                    strava_athlete_id,
                    access_token,
                    refresh_token,
                    expires_at,
                    scope,
                    created_at,
                    updated_at
                )
                values (
                    %s,
                    %s,
                    %s,
                    %s,
                    to_timestamp(%s),
                    %s,
                    now(),
                    now()
                )
                on conflict (user_id) do update set
                    strava_athlete_id = excluded.strava_athlete_id,
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    scope = excluded.scope,
                    expires_at = excluded.expires_at,
                    updated_at = now();
                """,
                (
                    state,
                    strava_athlete_id,
                    payload["access_token"],
                    payload["refresh_token"],
                    payload["expires_at"],
                    scope,
                ),
            )
            conn.commit()

    return {
        "ok": True,
        "user_id": state,
        "strava_athlete_id": strava_athlete_id,
        "scope": sorted(list(accepted_scopes)),
    }

@app.post("/debug/daily-readiness/{user_id}")
def debug_daily_readiness(user_id: str):
    try:
        sent = send_daily_readiness(user_id)
        return {"ok": True, "user_id": user_id, "sent": sent}
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"telegram error: {e}")
    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail=f"db error: {e}")

@app.post("/api/v1/healthkit/ingest/{user_id}", response_model=HealthIngestResponse)
def ingest_healthkit_payload(user_id: str, payload: HealthSyncPayload):
    try:
        save_healthkit_ingest_raw(user_id=user_id, payload=payload)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"failed to persist healthkit payload: {str(e)[:300]}",
        ) from e

    return HealthIngestResponse(
        user_id=user_id,
        sleep_nights_count=len(payload.sleepNights),
        resting_hr_count=len(payload.restingHeartRateDaily),
        hrv_count=len(payload.hrvSamples),
        latest_weight_included=payload.latestWeight is not None,
    )

@app.post("/api/v1/healthkit/process-latest/{user_id}")
def process_latest_healthkit_payload(user_id: str):
    return process_latest_healthkit_raw(user_id=user_id)


@app.post("/api/v1/healthkit/recovery-daily/{user_id}/{target_date}")
def recompute_health_recovery_daily_endpoint(user_id: str, target_date: str):
    return recompute_health_recovery_daily_for_date(
        user_id=user_id,
        target_date=target_date,
    )


@app.post("/api/v1/model/load-state-v2/{user_id}")
def recompute_load_state_daily_v2_endpoint(user_id: str):
    return recompute_load_state_daily_v2(user_id=user_id)


@app.post("/api/v1/model/readiness-daily/{user_id}/{target_date}")
def recompute_readiness_daily_endpoint(user_id: str, target_date: str):
    return recompute_readiness_daily_for_date(
        user_id=user_id,
        target_date=target_date,
    )


@app.post("/api/v1/healthkit/ingest-and-process/{user_id}")
def ingest_and_process_healthkit_payload_endpoint(user_id: str, payload: HealthSyncPayload):
    try:
        return ingest_and_process_healthkit_payload(
            user_id=user_id,
            payload=payload,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"failed to ingest and process healthkit payload: {str(e)[:300]}",
        ) from e
    

@app.post("/api/v1/healthkit/full-sync/{user_id}")
def full_sync_healthkit_payload_endpoint(user_id: str, payload: HealthSyncPayload):
    started_at = time.perf_counter()
    counts = {
        "sleep": len(payload.sleepNights),
        "hrv": len(payload.hrvSamples),
        "rhr": len(payload.restingHeartRateDaily),
    }

    log_event(
        logger,
        "healthkit_full_sync_started",
        user_id=user_id,
        counts=counts,
    )

    try:
        result = ingest_and_process_healthkit_payload(
            user_id=user_id,
            payload=payload,
        )
        log_event(
            logger,
            "healthkit_full_sync_finished",
            user_id=user_id,
            counts=counts,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"failed to run healthkit full sync: {str(e)[:300]}",
        ) from e


@app.get("/api/v1/model/readiness-daily/{user_id}/history")
def get_readiness_daily_history_endpoint(
    user_id: str,
    days: int = Query(default=7, ge=1, le=90),
):
    return get_readiness_daily_history(
        user_id=user_id,
        days=days,
    )


@app.get("/api/v1/model/readiness-daily/{user_id}/{target_date}")
def get_readiness_daily_endpoint(user_id: str, target_date: str):
    return get_readiness_daily_for_date(
        user_id=user_id,
        target_date=target_date,
    )
