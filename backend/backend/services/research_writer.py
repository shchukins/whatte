"""Dedicated, least-privilege research-result connection; no backend settings."""

import psycopg


def research_writer_connection(dsn):
    conn = psycopg.connect(dsn, connect_timeout=5,
                           options="-c search_path=pg_catalog,public -c statement_timeout=5000 -c lock_timeout=2000")
    try:
        with conn.cursor() as cur:
            # Refuse elevated accounts and inherited privileges. Credentials are
            # never included in candidate/evaluator requests or exception logs.
            cur.execute("""
                select exists (
                    select 1 from pg_roles r
                    where pg_has_role(current_user, r.oid, 'MEMBER')
                      and (r.rolsuper or r.rolcreatedb or r.rolcreaterole
                           or r.rolreplication or r.rolbypassrls)
                ), pg_has_role(current_user, 'whatte_research_writer', 'MEMBER');
            """)
            elevated, writer = cur.fetchone()
            if elevated or not writer:
                raise ValueError("research_writer_role_required")
            cur.execute("""
                select exists (
                    select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname not in ('pg_catalog', 'information_schema')
                      and n.nspname not like 'pg_toast%%'
                      and c.relkind in ('r', 'p', 'v', 'm', 'f')
                      and not (n.nspname = 'public' and c.relname = 'research_experiment')
                      and (has_table_privilege(c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE')
                           or has_any_column_privilege(c.oid, 'INSERT,UPDATE'))
                ) or exists (
                    select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                    where p.prosecdef and n.nspname not in ('pg_catalog', 'information_schema')
                      and has_function_privilege(p.oid, 'EXECUTE')
                ) or exists (
                    select 1 from pg_namespace n
                    where n.nspname not like 'pg_%%' and n.nspname <> 'information_schema'
                      and has_schema_privilege(n.oid, 'CREATE')
                );
            """)
            if cur.fetchone()[0]:
                raise ValueError("research_writer_has_unsafe_permissions")
        conn.commit()
        return conn
    except Exception:
        conn.close()
        raise
