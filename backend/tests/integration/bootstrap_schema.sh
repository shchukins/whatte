#!/usr/bin/env bash

set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
readonly DATABASE_URL="${DATABASE_URL:?DATABASE_URL must be set}"

# Base ingestion tables. The webhook table must exist before ingest jobs, and
# the raw activity table must exist before the deduplication migration.
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/ingestion/sql_user_strava_connection.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/ingestion/sql_strava_webhook_event.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/ingestion/sql_strava_activity_raw.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/ingestion/sql_healthkit_ingest_raw.sql"

# Ingest job, activity stream, and profile tables.
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/ingestion/sql_strava_activity_ingest_job.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/ingestion/sql_strava_activity_stream_raw.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/scratch/sql_user_training_profile.sql"

# Normalized health tables.
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/health/sql_health_sleep_night.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/health/sql_health_resting_hr_daily.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/health/sql_health_hrv_sample.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/health/sql_health_weight_measurement.sql"

# Derived metrics and daily state tables.
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/analytics/sql_activity_metrics.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/analytics/sql_activity_response_metrics.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/analytics/sql_daily_training_load.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/analytics/sql_daily_fitness_state.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/health/sql_health_recovery_daily.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/analytics/sql_load_state_daily_v2.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/analytics/sql_readiness_daily.sql"

# Base db-init tables required by the following ALTER TABLE migrations.
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/001_init.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/002_activity_subjective_feedback.sql"

# Schema alterations, applied only after their base tables exist.
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/sql/health/sql_health_recovery_daily_add_explanation_json.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/003_subjective_feedback_extensible.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/004_next_day_recovery_feedback.sql"

# Notification, feedback prompt, and indoor activity deduplication migrations.
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/005_subjective_feedback_prompt_log.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/006_notification_log.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/007_indoor_activity_deduplication.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/008_daily_readiness_delivery_lifecycle.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/009_activity_response_metrics.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/010_decision_context_snapshot.sql"

psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/011_user_profile.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/012_rpe_observations.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/013_manual_physiology_observations.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/014_telegram_physiology_checkin.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/015_personal_physiology_features.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/016_research_feature_snapshot.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/017_decision_context_snapshot_events.sql"
psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/018_research_experiment.sql"

psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/019_research_execution_metadata.sql"

psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f "$REPO_ROOT/db-init/020_user_profile_hr_max.sql"
