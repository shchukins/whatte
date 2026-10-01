"""HTTP contract for persisted manual physiology observations.

This router only stores and reads raw optional observations. It deliberately
does not calculate recovery or trigger readiness recomputation.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.config import settings
from backend.services.manual_physiology_service import (
    ManualPhysiologyObservation,
    ManualPhysiologyPatch,
    get_manual_physiology_observation,
    local_today,
    save_manual_physiology_observation,
)


router = APIRouter(prefix="/api/v1/manual-physiology", tags=["manual-physiology"])
_bearer = HTTPBearer(auto_error=False)
_VALUE_FIELDS = (
    "sleep_duration_minutes",
    "sleep_quality",
    "hrv_ms",
    "resting_hr_bpm",
)


def require_manual_physiology_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Require the dedicated token; an unset token never makes this API public."""
    expected_token = settings.manual_physiology_api_token
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="manual physiology API authentication is not configured",
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, expected_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid manual physiology API token",
            headers={"WWW-Authenticate": "Bearer"},
        )


class ManualPhysiologyUpdate(BaseModel):
    """Partial source submission; omitted values preserve a prior observation."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["telegram", "web"]
    sleep_duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    hrv_ms: float | None = Field(default=None, gt=0, le=500, allow_inf_nan=False)
    resting_hr_bpm: float | None = Field(
        default=None, ge=20, le=250, allow_inf_nan=False
    )
    observed_at: datetime | None = None

    @model_validator(mode="after")
    def require_aware_observation_time(self):
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return self


class PhysiologyField(BaseModel):
    availability: Literal["available", "unavailable"]
    value: int | float | None


class ManualPhysiologyResponse(BaseModel):
    available: bool
    local_date: date
    fields: dict[str, PhysiologyField]
    source: Literal["telegram", "web", "import"] | None
    observed_at: datetime | None
    schema_version: str | None
    revision: int | None
    created_at: datetime | None
    updated_at: datetime | None
    changed: bool | None = None
    changed_fields: list[str] | None = None


def _response(
    observation: ManualPhysiologyObservation | None,
    *,
    local_date: date,
    changed: bool | None = None,
    changed_fields: list[str] | None = None,
) -> ManualPhysiologyResponse:
    def field(name: str) -> PhysiologyField:
        value = getattr(observation, name) if observation is not None else None
        return PhysiologyField(
            availability="available" if value is not None else "unavailable",
            value=value,
        )

    return ManualPhysiologyResponse(
        available=observation is not None,
        local_date=local_date,
        fields={name: field(name) for name in _VALUE_FIELDS},
        source=observation.source if observation is not None else None,
        observed_at=observation.observed_at if observation is not None else None,
        schema_version=observation.schema_version if observation is not None else None,
        revision=observation.revision if observation is not None else None,
        created_at=observation.created_at if observation is not None else None,
        updated_at=observation.updated_at if observation is not None else None,
        changed=changed,
        changed_fields=changed_fields,
    )


@router.get("/{local_date}", response_model=ManualPhysiologyResponse)
def get_manual_physiology(
    local_date: date,
    _: None = Depends(require_manual_physiology_api_token),
):
    observation = get_manual_physiology_observation(
        user_id=settings.daily_readiness_user_id,
        local_date=local_date,
    )
    return _response(observation, local_date=local_date)


@router.patch("/{local_date}", response_model=ManualPhysiologyResponse)
def update_manual_physiology(
    local_date: date,
    update: ManualPhysiologyUpdate,
    _: None = Depends(require_manual_physiology_api_token),
):
    if local_date > local_today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="future local dates are not supported",
        )
    patch = ManualPhysiologyPatch(
        local_date=local_date,
        **update.model_dump(exclude_unset=True),
    )
    saved = save_manual_physiology_observation(
        user_id=settings.daily_readiness_user_id,
        patch=patch,
    )
    return _response(
        saved.observation,
        local_date=local_date,
        changed=saved.changed,
        changed_fields=saved.changed_fields,
    )
