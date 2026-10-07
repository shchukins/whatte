-- Nullable for existing #135 rows; metrics_json remains evaluator output only.
alter table research_experiment add column if not exists execution_metadata jsonb;
do $$
begin
    if not exists (select 1 from pg_constraint
                   where conrelid = 'research_experiment'::regclass
                     and conname = 'chk_research_execution_metadata') then
        alter table research_experiment add constraint chk_research_execution_metadata
        check (execution_metadata is null or
               (status <> 'running' and jsonb_typeof(execution_metadata) = 'object'));
    end if;
end;
$$;

-- This NOLOGIN role is only a permission group. Provision a dedicated LOGIN
-- externally with no other memberships, ownership, or elevated attributes.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'whatte_research_writer') then
        create role whatte_research_writer nologin nosuperuser nocreatedb
            nocreaterole noreplication nobypassrls;
    end if;
end;
$$;
grant usage on schema public to whatte_research_writer;
grant select on research_experiment to whatte_research_writer;
grant insert (experiment_id, parent_experiment_id, baseline_experiment_id,
    hypothesis, candidate_model_version, candidate_config, candidate_config_hash,
    dataset_version, dataset_hash, dataset_partition, evaluator_version,
    evaluator_specification_hash, status, provider_metadata, created_at, started_at)
    on research_experiment to whatte_research_writer;
grant update (status, finished_at, execution_duration_ms, metrics_json,
    failure_reason, failure_log_reference, execution_metadata)
    on research_experiment to whatte_research_writer;
grant usage on sequence research_experiment_id_seq to whatte_research_writer;
-- Existing lifecycle trigger blocks deletion and modification of terminal rows.
