from common.db import get_db_connection
import psycopg2.extras

def load_vessels():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT
            imo_no,
            customer,
            vessel_name,
            en_manu,
            en_mod,
            mcr_out,
            fil_pur,
            cylinders,
            responsible,
            priority
        FROM legacy_vessels
        ORDER BY vessel_name ASC
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [dict(r) for r in rows]