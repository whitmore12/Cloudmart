"""Shared helper for the database tests. This is not a test module.

Other tests in this folder rebuild the same tables with fewer columns, so each
database test starts from an empty schema and lets the app create its own tables.
It refuses to run unless the database name contains "test".

Author: Claude (Anthropic)
"""

import psycopg

def reset_database(dsn):
    """Empties the throwaway database so init_db builds the real tables from scratch."""
    assert "test" in dsn.lower(), "refusing to wipe a database without test in its name"
    conn = psycopg.connect(dsn)
    conn.execute("DROP SCHEMA public CASCADE")
    conn.execute("CREATE SCHEMA public")
    conn.commit()
    conn.close()
