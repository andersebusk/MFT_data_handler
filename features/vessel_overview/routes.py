from flask import Blueprint, render_template, jsonify
import os
import psycopg2
import psycopg2.extras
import traceback

vessel_overview_bp = Blueprint("vessel_overview", __name__)


def get_db_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(database_url, sslmode="require")


@vessel_overview_bp.route("/vessel-overview", methods=["GET"])
def vessel_overview_page():
    return render_template("vessel_overview.html")


@vessel_overview_bp.route("/api/vessel-overview/data", methods=["GET"])
def vessel_overview_data():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        sql = """
            WITH fd AS (
                SELECT
                    imo_no::text AS imo_no_txt,
                    MAX(fb_date) AS latest_feedback_date
                FROM feedback_data
                WHERE imo_no IS NOT NULL
                AND COALESCE(is_deleted, FALSE) = FALSE
                GROUP BY imo_no::text
            ),
            sd AS (
                SELECT
                    imo_no::text AS imo_no_txt,
                    MAX(scav_date) AS latest_scavenge_date
                FROM scavenge_data
                WHERE imo_no IS NOT NULL
                AND COALESCE(is_deleted, FALSE) = FALSE
                GROUP BY imo_no::text
            ),
            sl AS (
                SELECT
                    imo_no::text AS imo_no_txt,
                    MAX(lab_date) AS latest_scrape_lab_date
                FROM scrape_lab
                WHERE imo_no IS NOT NULL
                AND COALESCE(is_deleted, FALSE) = FALSE
                GROUP BY imo_no::text
            ),
            ms AS (
                SELECT
                    imo_no::text AS imo_no_txt,
                    MAX(sys_date) AS latest_me_sys_date
                FROM me_sys_data
                WHERE imo_no IS NOT NULL
                AND COALESCE(is_deleted, FALSE) = FALSE
                GROUP BY imo_no::text
            ),
            kpi AS (
                SELECT
                    imo_no::text AS imo_no_txt,
                    MAX(feedback_received_at) AS latest_feedback_received_at,
                    MAX(report_generated_at) AS latest_report_generated_at
                FROM kpi_data
                WHERE imo_no IS NOT NULL
                AND COALESCE(is_deleted, FALSE) = FALSE
                GROUP BY imo_no::text
            )
            SELECT
                lv.customer,
                lv.vessel_name,
                lv.responsible,
                lv.imo_no,
                lv.priority,

                fd.latest_feedback_date,
                sd.latest_scavenge_date,
                sl.latest_scrape_lab_date,
                ms.latest_me_sys_date,
                kpi.latest_feedback_received_at,
                kpi.latest_report_generated_at,

                CASE
                    WHEN fd.latest_feedback_date IS NULL THEN NULL
                    ELSE (CURRENT_DATE - fd.latest_feedback_date::date)
                END AS latest_feedback_date_days,

                CASE
                    WHEN sd.latest_scavenge_date IS NULL THEN NULL
                    ELSE (CURRENT_DATE - sd.latest_scavenge_date::date)
                END AS latest_scavenge_date_days,

                CASE
                    WHEN sl.latest_scrape_lab_date IS NULL THEN NULL
                    ELSE (CURRENT_DATE - sl.latest_scrape_lab_date::date)
                END AS latest_scrape_lab_date_days,

                CASE
                    WHEN ms.latest_me_sys_date IS NULL THEN NULL
                    ELSE (CURRENT_DATE - ms.latest_me_sys_date::date)
                END AS latest_me_sys_date_days,

                CASE
                    WHEN kpi.latest_feedback_received_at IS NULL THEN NULL
                    ELSE (CURRENT_DATE - kpi.latest_feedback_received_at::date)
                END AS latest_feedback_received_at_days,

                CASE
                    WHEN kpi.latest_report_generated_at IS NULL THEN NULL
                    ELSE (CURRENT_DATE - kpi.latest_report_generated_at::date)
                END AS latest_report_generated_at_days

            FROM legacy_vessels lv
            LEFT JOIN fd  ON fd.imo_no_txt  = lv.imo_no::text
            LEFT JOIN sd  ON sd.imo_no_txt  = lv.imo_no::text
            LEFT JOIN sl  ON sl.imo_no_txt  = lv.imo_no::text
            LEFT JOIN ms  ON ms.imo_no_txt  = lv.imo_no::text
            LEFT JOIN kpi ON kpi.imo_no_txt = lv.imo_no::text
            ORDER BY
                lv.priority ASC NULLS LAST,
                lv.customer ASC NULLS LAST,
                lv.vessel_name ASC NULLS LAST
        """

        cur.execute(sql)
        rows = cur.fetchall()

        columns = [
            {"data": "customer", "title": "Customer"},
            {"data": "vessel_name", "title": "Vessel Name"},
            {"data": "responsible", "title": "Responsible"},
            {"data": "imo_no", "title": "IMO Number"},
            {"data": "latest_feedback_date_days", "title": "Feedback Date"},
            {"data": "latest_scavenge_date_days", "title": "Scavenge Date"},
            {"data": "latest_scrape_lab_date_days", "title": "Scrape Lab Date"},
            {"data": "latest_me_sys_date_days", "title": "ME System Oil Date"},
            {"data": "latest_feedback_received_at_days", "title": "Feedback Received"},
            {"data": "latest_report_generated_at_days", "title": "Report Generated"},
            {"data": "priority", "title": "Priority"},
        ]

        return jsonify({
            "ok": True,
            "columns": columns,
            "rows": rows
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "ok": False,
            "error_type": type(e).__name__,
            "error": str(e)
        }), 500

    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()