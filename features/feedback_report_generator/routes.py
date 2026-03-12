from flask import Blueprint, request, jsonify, send_from_directory
from datetime import datetime, timezone
from common.auth import requires_auth
from common.s3 import get_s3_client, get_bucket_name
from common.vessels import load_vessels
from common.pdfgen import generate_pdf
import psycopg2.extras
from decimal import Decimal

from common.db import get_db_connection

bp = Blueprint("feedback_report_generator", __name__)

@bp.route("/upload-image", methods=["POST"])
@requires_auth
def upload_image():
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "No file provided"}), 400

    s3_client = get_s3_client()
    bucket = get_bucket_name()

    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        filename = f"{timestamp}_{file.filename}"

        s3_client.upload_fileobj(
            file,
            bucket,
            filename,
            ExtraArgs={"ContentType": file.content_type},
        )

        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": filename},
            ExpiresIn=604800,
        )
        return jsonify({"url": presigned_url})
    except Exception as e:
        print("S3 upload error:", repr(e))
        return jsonify({"error": f"Upload failed: {e}"}), 500

@bp.route("/vessels", methods=["GET"])
@requires_auth
def get_vessels():
    return jsonify(load_vessels())

@bp.route("/feedback-registrations", methods=["GET"])
@requires_auth
def feedback_registrations():
    """Return latest feedback registrations + KPI status so the generator can link by register_id."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT
                f.register_id,
                k.created_by,
                f.vessel_name,
                f.imo_no,
                MAX(f.created_at) AS created_at,
                k.feedback_received_at,
                k.report_generated_at
            FROM public.feedback_data f
            LEFT JOIN public.kpi_data k
              ON k.register_id = f.register_id
            WHERE f.register_id IS NOT NULL
            AND f.register_id <> ''
            AND f.is_deleted = false
            AND (k.is_deleted IS NULL OR k.is_deleted = false)
            GROUP BY f.register_id, k.created_by, f.vessel_name, f.imo_no, k.feedback_received_at, k.report_generated_at
            ORDER BY MAX(f.created_at) DESC
            LIMIT 50
        """)

        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows)

    except Exception as e:
        print("feedback-registrations ERROR:", e)
        return jsonify({"error": str(e)}), 500


@bp.route("/feedback-report-autofill/<register_id>", methods=["GET"])
@requires_auth
def feedback_report_autofill(register_id):
    def _safe_float(value):
        if value is None or value == "":
            return None
        if isinstance(value, Decimal):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _fmt_date(value):
        if value is None or value == "":
            return None
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        return str(value)

    def _flatten_numeric_values(values):
        nums = []
        def _walk(v):
            if v is None or v == "":
                return
            if isinstance(v, (list, tuple)):
                for item in v:
                    _walk(item)
                return
            n = _safe_float(v)
            if n is not None:
                nums.append(n)
        for value in values:
            _walk(value)
        return nums

    def _avg(values):
        nums = _flatten_numeric_values(values)
        if not nums:
            return None
        return round(sum(nums) / len(nums), 2)

    def _pick_cols(row, prefixes):
        if not row:
            return []
        cols = []
        for key in row.keys():
            k = (key or "").lower()
            if any(k.startswith(p) for p in prefixes):
                cols.append(key)
        return sorted(cols)

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT *
            FROM public.feedback_data
            WHERE register_id = %s
              AND COALESCE(is_deleted, false) = false
            ORDER BY fb_date ASC NULLS LAST, created_at ASC NULLS LAST
            """,
            (register_id,)
        )
        rows = cur.fetchall()
        if not rows:
            cur.close()
            conn.close()
            return jsonify({"error": "No feedback rows found for register_id"}), 404

        first_row = rows[0]
        latest_row = rows[-1]
        imo_no = latest_row.get("imo_no") or first_row.get("imo_no")
        created_by = latest_row.get("created_by") or first_row.get("created_by")
        if not created_by:
            try:
                cur.execute("SELECT created_by FROM public.kpi_data WHERE register_id = %s LIMIT 1", (register_id,))
                kpi_row = cur.fetchone() or {}
                created_by = kpi_row.get("created_by")
            except Exception as kpi_err:
                conn.rollback()
                print("kpi_data lookup warning:", kpi_err)

        cur.execute(
            """
            SELECT cyl_oil_feed_rate
            FROM public.feedback_data
            WHERE CAST(imo_no AS text) = CAST(%s AS text)
              AND COALESCE(is_deleted, false) = false
            ORDER BY fb_date ASC NULLS LAST, created_at ASC NULLS LAST
            LIMIT 1
            """,
            (imo_no,)
        )
        oldest_imo_row = cur.fetchone() or {}

        latest_lab_date = None
        try:
            cur.execute(
                """
                SELECT MAX(lab_date) AS latest_lab_date
                FROM public.scrape_lab
                WHERE CAST(imo_no AS text) = CAST(%s AS text)
                """,
                (imo_no,)
            )
            lab_row = cur.fetchone() or {}
            latest_lab_date = lab_row.get("latest_lab_date")
        except Exception as lab_err:
            conn.rollback()
            print("scrape_lab lookup warning:", lab_err)
            latest_lab_date = None

        cur.close()
        conn.close()

        res_tbn_cols = _pick_cols(latest_row, ["res_tbn", "residual_tbn", "res_bn"])
        fe_tot_cols = _pick_cols(latest_row, ["fe_tot", "fe_total"])

        payload = {
            "register_id": register_id,
            "created_by": created_by,
            "imo_no": imo_no,
            "date_of_report": datetime.now().strftime("%Y-%m-%d"),
            "sample_period_from": _fmt_date(next((r.get("fb_date") for r in rows if r.get("fb_date") is not None), None)),
            "sample_period_to": _fmt_date(next((r.get("fb_date") for r in reversed(rows) if r.get("fb_date") is not None), None)),
            "latest_onboard_sample_date": _fmt_date(next((r.get("fb_date") for r in reversed(rows) if r.get("fb_date") is not None), None)),
            "latest_lab_sample_date": _fmt_date(latest_lab_date),
            "avg_load": _avg([r.get("me_load") for r in rows]),
            "fuel_sulph": _safe_float(latest_row.get("fuel_sulph")),
            "clo_bn": _safe_float(latest_row.get("tbn_fed")),
            "avg_clo_24hrs": _avg([r.get("daily_cyl_oil_cons") for r in rows]),
            "acc_factor": _safe_float(latest_row.get("acc_factor")),
            "feedrate_before_bob": _safe_float(oldest_imo_row.get("cyl_oil_feed_rate")),
            "latest_feedrate": _safe_float(latest_row.get("cyl_oil_feed_rate")),
            "avg_res_tbn": _avg([r.get(col) for r in rows for col in res_tbn_cols]),
            "avg_fe_tot": _avg([r.get(col) for r in rows for col in fe_tot_cols]),
            "res_tbn_columns": res_tbn_cols,
            "fe_tot_columns": fe_tot_cols,
        }
        return jsonify(payload)

    except Exception as e:
        print("feedback-report-autofill ERROR:", repr(e))
        return jsonify({"error": str(e)}), 500

@bp.route("/generate-pdf", methods=["POST"])
@requires_auth
def generate_pdf_route():
    try:
        payload = request.json
        result = generate_pdf(payload)
        return jsonify({"pdfUrl": result.get("response")})
    except Exception as e:
        print("PDF generation error:", e)
        return jsonify({"error": "PDF generation failed"}), 500

@bp.route("/", methods=["GET"])
@requires_auth
def serve_dashboard():
    return send_from_directory("templates", "dashboard.html")

@bp.route("/feedback-report-generator", methods=["GET"])
@requires_auth
def serve_feedback_report_generator():
    return send_from_directory("templates", "feedback_report_generator.html")
