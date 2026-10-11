-- Preserved auxiliary production objects, catalog-only export (no rows).
-- vector; Type: EXTENSION; Schema: -; Owner: -
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

-- EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';

-- daily_state; Type: VIEW; Schema: analytics; Owner: -
CREATE SCHEMA analytics;

CREATE VIEW analytics.daily_state AS
 WITH days AS (
         SELECT readiness_daily.user_id,
            readiness_daily.date
           FROM public.readiness_daily
        UNION
         SELECT health_recovery_daily.user_id,
            health_recovery_daily.date
           FROM public.health_recovery_daily
        UNION
         SELECT load_state_daily_v2.user_id,
            load_state_daily_v2.date
           FROM public.load_state_daily_v2
        )
 SELECT d.user_id,
    d.date,
    r.readiness_score,
    r.good_day_probability,
    r.status_text AS readiness_status,
    r.freshness AS readiness_freshness,
    r.recovery_score_simple AS readiness_recovery_score,
    r.version AS readiness_version,
    rec.sleep_minutes,
    rec.awake_minutes,
    rec.rem_minutes,
    rec.deep_minutes,
    rec.resting_hr_bpm,
    rec.hrv_daily_median_ms,
    rec.weight_kg,
    rec.recovery_score_simple,
    COALESCE(t.activities_count, 0) AS activities_count,
    COALESCE(t.duration_s, 0) AS training_duration_s,
    COALESCE(t.distance_m, (0)::double precision) AS distance_m,
    COALESCE(t.elevation_gain_m, (0)::double precision) AS elevation_gain_m,
    COALESCE(t.work_kj, (0)::double precision) AS work_kj,
    COALESCE(t.tss, (0)::double precision) AS daily_tss,
    l.load_input_nonlinear,
    l.fitness,
    l.fatigue_fast,
    l.fatigue_slow,
    l.fatigue_total,
    l.freshness,
    l.version AS load_model_version,
        CASE
            WHEN ((rec.sleep_minutes + rec.awake_minutes) > (0)::double precision) THEN (((100.0)::double precision * rec.sleep_minutes) / (rec.sleep_minutes + rec.awake_minutes))
            ELSE NULL::double precision
        END AS sleep_efficiency_pct,
        CASE
            WHEN (rec.sleep_minutes > (0)::double precision) THEN (((100.0)::double precision * rec.deep_minutes) / rec.sleep_minutes)
            ELSE NULL::double precision
        END AS deep_sleep_pct,
        CASE
            WHEN (rec.sleep_minutes > (0)::double precision) THEN (((100.0)::double precision * rec.rem_minutes) / rec.sleep_minutes)
            ELSE NULL::double precision
        END AS rem_sleep_pct
   FROM ((((days d
     LEFT JOIN public.readiness_daily r ON (((r.user_id = d.user_id) AND (r.date = d.date))))
     LEFT JOIN public.health_recovery_daily rec ON (((rec.user_id = d.user_id) AND (rec.date = d.date))))
     LEFT JOIN public.daily_training_load t ON (((t.user_id = d.user_id) AND (t.date = d.date))))
     LEFT JOIN public.load_state_daily_v2 l ON (((l.user_id = d.user_id) AND (l.date = d.date))));

-- document; Type: TABLE; Schema: public; Owner: -
CREATE TABLE public.document (
    id bigint NOT NULL,
    source text NOT NULL,
    external_id text,
    title text NOT NULL,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- document_chunk; Type: TABLE; Schema: public; Owner: -
CREATE TABLE public.document_chunk (
    id bigint NOT NULL,
    document_id bigint NOT NULL,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    embedding public.vector(768),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- document_chunk_id_seq; Type: SEQUENCE; Schema: public; Owner: -
CREATE SEQUENCE public.document_chunk_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- document_chunk_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
ALTER SEQUENCE public.document_chunk_id_seq OWNED BY public.document_chunk.id;

-- document_id_seq; Type: SEQUENCE; Schema: public; Owner: -
CREATE SEQUENCE public.document_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- document_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
ALTER SEQUENCE public.document_id_seq OWNED BY public.document.id;

-- document id; Type: DEFAULT; Schema: public; Owner: -
ALTER TABLE ONLY public.document ALTER COLUMN id SET DEFAULT nextval('public.document_id_seq'::regclass);

-- document_chunk id; Type: DEFAULT; Schema: public; Owner: -
ALTER TABLE ONLY public.document_chunk ALTER COLUMN id SET DEFAULT nextval('public.document_chunk_id_seq'::regclass);

-- document_chunk document_chunk_pkey; Type: CONSTRAINT; Schema: public; Owner: -
ALTER TABLE ONLY public.document_chunk
    ADD CONSTRAINT document_chunk_pkey PRIMARY KEY (id);

-- document document_pkey; Type: CONSTRAINT; Schema: public; Owner: -
ALTER TABLE ONLY public.document
    ADD CONSTRAINT document_pkey PRIMARY KEY (id);

-- document_chunk document_chunk_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
ALTER TABLE ONLY public.document_chunk
    ADD CONSTRAINT document_chunk_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.document(id) ON DELETE CASCADE;

CREATE INDEX idx_document_chunk_document_id ON public.document_chunk USING btree (document_id);
-- Fresh installations preserve the existing read-only privilege group. Login
-- credentials and role login activation remain externally provisioned.
do $$ begin
    if not exists (select 1 from pg_roles where rolname = 'superset_reader') then
        create role superset_reader nologin nosuperuser nocreatedb nocreaterole
            noreplication nobypassrls;
    end if;
end $$;
grant usage on schema public, analytics to superset_reader;
grant select on all tables in schema public, analytics to superset_reader;
alter default privileges in schema public grant select on tables to superset_reader;
