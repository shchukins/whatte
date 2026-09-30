"""Versioned persistence for optional manually entered physiology."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.config import settings
from backend.db import get_conn


MANUAL_PHYSIOLOGY_SCHEMA_VERSION = "manual_physiology_observation_v1"
MANUAL_PHYSIOLOGY_SOURCES = ("telegram", "web", "import")
VALUE_FIELDS = (
    "sleep_duration_minutes",
    "sleep_quality",
    "hrv_ms",
    "resting_hr_bpm",
)
EDITABLE_FIELDS = (*VALUE_FIELDS, "observed_at")


def local_today(
    *, now: datetime | None = None, timezone: str | None = None
) -> date:
    zone = ZoneInfo(timezone or settings.whatte_timezone)
    current = now or datetime.now(zone)
    if current.tzinfo is None:
        raise ValueError("now must include a timezone")
    return current.astimezone(zone).date()


class ManualPhysiologyPatch(BaseModel):
    """One source submission for a local day.

    Pydantic's ``model_fields_set`` distinguishes an omitted value from an
    explicit ``None``: omitted fields retain their current value, while null
    clears a value and records that edit in the revision history.
    """

    model_config = ConfigDict(extra="forbid")

    local_date: date
    source: Literal["telegram", "web", "import"]
    sleep_duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    hrv_ms: float | None = Field(default=None, gt=0, le=500, allow_inf_nan=False)
    resting_hr_bpm: float | None = Field(
        default=None, ge=20, le=250, allow_inf_nan=False
    )
    observed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.local_date > local_today():
            raise ValueError("Future local dates are not supported")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return self


class ManualPhysiologyObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    user_id: str
    local_date: date
    sleep_duration_minutes: int | None
    sleep_quality: int | None
    hrv_ms: float | None
    resting_hr_bpm: float | None
    source: Literal["telegram", "web", "import"]
    observed_at: datetime | None
    schema_version: Literal["manual_physiology_observation_v1"]
    revision: int
    created_at: datetime
    updated_at: datetime


class ManualPhysiologySaveResult(BaseModel):
    observation: ManualPhysiologyObservation
    changed: bool
    changed_fields: list[str]


_SELECT_COLUMNS = """
    id, user_id, local_date, sleep_duration_minutes, sleep_quality,
    hrv_ms, resting_hr_bpm, source, observed_at, schema_version,
    revision, created_at, updated_at
"""


def _row_to_observation(row: tuple[Any, ...]) -> ManualPhysiologyObservation:
    return ManualPhysiologyObservation.model_validate(dict(zip(
        (
            "id", "user_id", "local_date", "sleep_duration_minutes",
            "sleep_quality", "hrv_ms", "resting_hr_bpm", "source",
            "observed_at", "schema_version", "revision", "created_at",
            "updated_at",
        ),
        row,
    )))


def _merge_patch(
    current: ManualPhysiologyObservation | None,
    patch: ManualPhysiologyPatch,
) -> tuple[dict[str, Any], list[str]]:
    values = {
        field: getattr(current, field) if current is not None else None
        for field in EDITABLE_FIELDS
    }
    submitted = patch.model_fields_set.intersection(EDITABLE_FIELDS)
    changed_fields = []
    for field in EDITABLE_FIELDS:
        if field not in submitted:
            continue
        incoming = getattr(patch, field)
        if current is None or incoming != values[field]:
            values[field] = incoming
            changed_fields.append(field)

    if current is None or current.source != patch.source:
        changed_fields.append("source")
    values["source"] = patch.source
    return values, changed_fields


def get_manual_physiology_observation(
    *, user_id: str, local_date: date
) -> ManualPhysiologyObservation | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select {_SELECT_COLUMNS}
                from manual_physiology_observation
                where user_id = %s and local_date = %s;
                """,
                (user_id, local_date),
            )
            row = cur.fetchone()
    return _row_to_observation(row) if row is not None else None


def save_manual_physiology_observation(
    *, user_id: str, patch: ManualPhysiologyPatch
) -> ManualPhysiologySaveResult:
    """Create or edit one daily row and append a revision only on change."""
    if not user_id or not user_id.strip():
        raise ValueError("user_id is required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            lock_key = f"manual-physiology:{user_id}:{patch.local_date.isoformat()}"
            cur.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0));",
                (lock_key,),
            )
            cur.execute(
                f"""
                select {_SELECT_COLUMNS}
                from manual_physiology_observation
                where user_id = %s and local_date = %s
                for update;
                """,
                (user_id, patch.local_date),
            )
            row = cur.fetchone()
            current = _row_to_observation(row) if row is not None else None
            values, changed_fields = _merge_patch(current, patch)

            if current is not None and not changed_fields:
                conn.commit()
                return ManualPhysiologySaveResult(
                    observation=current,
                    changed=False,
                    changed_fields=[],
                )

            params = (
                values["sleep_duration_minutes"],
                values["sleep_quality"],
                values["hrv_ms"],
                values["resting_hr_bpm"],
                values["source"],
                values["observed_at"],
                MANUAL_PHYSIOLOGY_SCHEMA_VERSION,
            )
            if current is None:
                cur.execute(
                    f"""
                    insert into manual_physiology_observation (
                        user_id, local_date, sleep_duration_minutes,
                        sleep_quality, hrv_ms, resting_hr_bpm, source,
                        observed_at, schema_version
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning {_SELECT_COLUMNS};
                    """,
                    (user_id, patch.local_date, *params),
                )
            else:
                cur.execute(
                    f"""
                    update manual_physiology_observation set
                        sleep_duration_minutes = %s,
                        sleep_quality = %s,
                        hrv_ms = %s,
                        resting_hr_bpm = %s,
                        source = %s,
                        observed_at = %s,
                        schema_version = %s,
                        revision = revision + 1,
                        updated_at = now()
                    where id = %s
                    returning {_SELECT_COLUMNS};
                    """,
                    (*params, current.id),
                )
            saved = _row_to_observation(cur.fetchone())
            cur.execute(
                """
                insert into manual_physiology_observation_revision (
                    observation_id, user_id, local_date, revision,
                    sleep_duration_minutes, sleep_quality, hrv_ms,
                    resting_hr_bpm, source, observed_at, schema_version,
                    changed_fields, received_at
                ) values (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s
                );
                """,
                (
                    saved.id, saved.user_id, saved.local_date, saved.revision,
                    saved.sleep_duration_minutes, saved.sleep_quality,
                    saved.hrv_ms, saved.resting_hr_bpm, saved.source,
                    saved.observed_at, saved.schema_version, changed_fields,
                    saved.updated_at,
                ),
            )
            conn.commit()

    return ManualPhysiologySaveResult(
        observation=saved,
        changed=True,
        changed_fields=changed_fields,
    )
