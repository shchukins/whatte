-- Research-only audit records. These rows describe offline experiments; they
-- must never contain source payloads, feature vectors, predictions, or mutate
-- user-facing production state.
create table if not exists research_experiment (
    id bigserial primary key,
    experiment_id text not null unique,
    parent_experiment_id text references research_experiment (experiment_id),
    baseline_experiment_id text references research_experiment (experiment_id),
    hypothesis text not null,
    candidate_model_version text not null,
    candidate_config jsonb not null,
    candidate_config_hash text not null,
    dataset_version text not null,
    dataset_hash text not null,
    dataset_partition text not null,
    evaluator_version text not null,
    evaluator_specification_hash text not null,
    status text not null,
    metrics_json jsonb,
    failure_reason text,
    failure_log_reference text,
    provider_metadata jsonb,
    created_at timestamptz not null default now(),
    started_at timestamptz not null,
    finished_at timestamptz,
    execution_duration_ms bigint,
    constraint chk_research_experiment_id_nonempty
        check (length(btrim(experiment_id)) > 0),
    constraint chk_research_experiment_parent_not_self
        check (parent_experiment_id is null or parent_experiment_id <> experiment_id),
    constraint chk_research_experiment_baseline_not_self
        check (baseline_experiment_id is null or baseline_experiment_id <> experiment_id),
    constraint chk_research_experiment_candidate_config_object
        check (jsonb_typeof(candidate_config) = 'object'),
    constraint chk_research_experiment_metrics_object
        check (metrics_json is null or jsonb_typeof(metrics_json) = 'object'),
    constraint chk_research_experiment_provider_metadata_object
        check (provider_metadata is null or jsonb_typeof(provider_metadata) = 'object'),
    constraint chk_research_experiment_partition
        check (dataset_partition in ('train', 'validation', 'test')),
    constraint chk_research_experiment_status
        check (status in ('running', 'rejected', 'candidate', 'failed', 'promoted')),
    constraint chk_research_experiment_time_order
        check (created_at <= started_at and (finished_at is null or started_at <= finished_at)),
    constraint chk_research_experiment_terminal_state
        check (
            (status = 'running'
                and finished_at is null
                and execution_duration_ms is null
                and metrics_json is null
                and failure_reason is null
                and failure_log_reference is null)
            or
            (status in ('candidate', 'rejected', 'promoted')
                and finished_at is not null
                and execution_duration_ms is not null
                and execution_duration_ms >= 0
                and metrics_json is not null
                and failure_reason is null
                and failure_log_reference is null)
            or
            (status = 'failed'
                and finished_at is not null
                and execution_duration_ms is not null
                and execution_duration_ms >= 0
                and metrics_json is null
                and failure_reason is not null
                and length(btrim(failure_reason)) > 0)
        )
);

create index if not exists ix_research_experiment_status_created
    on research_experiment (status, created_at, id);

create index if not exists ix_research_experiment_parent
    on research_experiment (parent_experiment_id)
    where parent_experiment_id is not null;

create or replace function protect_research_experiment_audit_log()
returns trigger
language plpgsql
as $$
begin
    if tg_op = 'INSERT' then
        if new.status <> 'running' then
            raise exception 'research experiment must be created as running';
        end if;
        return new;
    end if;

    if tg_op = 'DELETE' then
        raise exception 'research experiment audit rows cannot be deleted';
    end if;

    if old.status <> 'running' then
        raise exception 'terminal research experiment rows are immutable';
    end if;

    if new.status not in ('candidate', 'rejected', 'failed') then
        raise exception 'research experiment must transition from running to candidate, rejected, or failed';
    end if;

    if new.experiment_id is distinct from old.experiment_id
       or new.parent_experiment_id is distinct from old.parent_experiment_id
       or new.baseline_experiment_id is distinct from old.baseline_experiment_id
       or new.hypothesis is distinct from old.hypothesis
       or new.candidate_model_version is distinct from old.candidate_model_version
       or new.candidate_config is distinct from old.candidate_config
       or new.candidate_config_hash is distinct from old.candidate_config_hash
       or new.dataset_version is distinct from old.dataset_version
       or new.dataset_hash is distinct from old.dataset_hash
       or new.dataset_partition is distinct from old.dataset_partition
       or new.evaluator_version is distinct from old.evaluator_version
       or new.evaluator_specification_hash is distinct from old.evaluator_specification_hash
       or new.provider_metadata is distinct from old.provider_metadata
       or new.created_at is distinct from old.created_at
       or new.started_at is distinct from old.started_at then
        raise exception 'research experiment input metadata is immutable';
    end if;

    return new;
end;
$$;

drop trigger if exists trg_protect_research_experiment_audit_log on research_experiment;
create trigger trg_protect_research_experiment_audit_log
before insert or update or delete on research_experiment
for each row execute function protect_research_experiment_audit_log();
