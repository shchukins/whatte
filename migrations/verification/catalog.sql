-- Catalog only: no private rows. Physical column order and sequence values are
-- intentionally excluded; sequence definitions/ownership are checked instead.
WITH namespaces AS (
    SELECT oid, nspname, nspowner, nspacl FROM pg_namespace
    WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema'
), relations AS (
    SELECT c.*, n.nspname FROM pg_class c JOIN namespaces n ON n.oid = c.relnamespace
    WHERE c.relname <> 'flyway_schema_history'
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                      AND d.objid = c.oid AND d.deptype = 'e')
), objects AS (
    SELECT 'schema/' || nspname AS key,
           jsonb_build_object('owner', pg_get_userbyid(nspowner), 'acl', (SELECT jsonb_agg(v ORDER BY v::text) FROM unnest(nspacl) v)) AS value
    FROM namespaces
    UNION ALL
    SELECT 'relation/' || nspname || '/' || relname,
           jsonb_build_object('kind', relkind, 'owner', pg_get_userbyid(relowner),
                             'acl', (SELECT jsonb_agg(v ORDER BY v::text) FROM unnest(relacl) v), 'rls', relrowsecurity,
                             'force_rls', relforcerowsecurity, 'options', reloptions)
    FROM relations WHERE relkind IN ('r', 'p', 'v', 'm', 'S')
    UNION ALL
    SELECT 'column/' || c.nspname || '/' || c.relname || '/' || a.attname,
           jsonb_build_object('type', format_type(a.atttypid, a.atttypmod),
               'not_null', a.attnotnull, 'default', pg_get_expr(d.adbin, d.adrelid),
               'acl', (SELECT jsonb_agg(v ORDER BY v::text) FROM unnest(a.attacl) v), 'identity', a.attidentity, 'generated', a.attgenerated,
               'collation', a.attcollation::regcollation::text)
    FROM relations c JOIN pg_attribute a ON a.attrelid = c.oid
    LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
    WHERE a.attnum > 0 AND NOT a.attisdropped AND c.relkind IN ('r', 'p', 'v', 'm')
    UNION ALL
    SELECT 'constraint/' || c.nspname || '/' || c.relname || '/' || x.conname,
           jsonb_build_object('definition', pg_get_constraintdef(x.oid), 'validated', x.convalidated)
    FROM relations c JOIN pg_constraint x ON x.conrelid = c.oid
    UNION ALL
    SELECT 'index/' || c.nspname || '/' || c.relname || '/' || i.relname,
           jsonb_build_object('definition', pg_get_indexdef(x.indexrelid),
                             'valid', x.indisvalid, 'ready', x.indisready)
    FROM relations c JOIN pg_index x ON x.indrelid = c.oid JOIN pg_class i ON i.oid = x.indexrelid
    WHERE c.relname <> 'flyway_schema_history'
    UNION ALL
    SELECT 'sequence/' || c.nspname || '/' || c.relname,
           jsonb_build_object('type', format_type(s.seqtypid, NULL), 'start', s.seqstart,
               'increment', s.seqincrement, 'min', s.seqmin, 'max', s.seqmax,
               'cache', s.seqcache, 'cycle', s.seqcycle,
               'owned_by', (SELECT refobjid::regclass::text || '.' || a.attname
                   FROM pg_depend d JOIN pg_attribute a ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
                   WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype IN ('a','i')))
    FROM relations c JOIN pg_sequence s ON s.seqrelid = c.oid
    UNION ALL
    SELECT 'view/' || nspname || '/' || relname, to_jsonb(pg_get_viewdef(oid, false))
    FROM relations WHERE relkind IN ('v', 'm')
    UNION ALL
    SELECT 'function/' || n.nspname || '/' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
           jsonb_build_object('definition', pg_get_functiondef(p.oid), 'owner', pg_get_userbyid(p.proowner), 'acl', (SELECT jsonb_agg(v ORDER BY v::text) FROM unnest(p.proacl) v))
    FROM pg_proc p JOIN namespaces n ON n.oid = p.pronamespace
    WHERE p.prokind IN ('f','p') AND NOT EXISTS (
        SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')
    UNION ALL
    SELECT 'trigger/' || c.nspname || '/' || c.relname || '/' || t.tgname,
           jsonb_build_object('definition', pg_get_triggerdef(t.oid), 'enabled', t.tgenabled)
    FROM relations c JOIN pg_trigger t ON t.tgrelid = c.oid WHERE NOT t.tgisinternal
    UNION ALL
    SELECT 'default_acl/' || r.rolname || '/' || n.nspname || '/' || d.defaclobjtype::text,
           (SELECT jsonb_agg(v ORDER BY v::text) FROM unnest(d.defaclacl) v)
    FROM pg_default_acl d JOIN pg_roles r ON r.oid = d.defaclrole JOIN namespaces n ON n.oid = d.defaclnamespace
    UNION ALL
    SELECT 'extension/' || e.extname, jsonb_build_object('version', e.extversion,
           'schema', n.nspname, 'owner', pg_get_userbyid(e.extowner))
    FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
)
SELECT jsonb_object_agg(key, value ORDER BY key) FROM objects;
