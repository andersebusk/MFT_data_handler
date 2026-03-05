from flask import Blueprint, request, jsonify, send_from_directory
from datetime import datetime, timezone
from common.auth import requires_auth
from common.s3 import get_s3_client, get_bucket_name
from common.vessels import load_vessels
from common.pdfgen import generate_pdf
import psycopg2.extras

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
              f.vessel_name,
              f.imo_no,
              MAX(f.created_at) AS created_at,
              k.feedback_received_at,
              k.report_generated_at
            FROM public.feedback_data f
            LEFT JOIN public.kpi_data k
              ON k.register_id = f.register_id
            WHERE f.register_id IS NOT NULL AND f.register_id <> ''
            GROUP BY f.register_id, f.vessel_name, f.imo_no, k.feedback_received_at, k.report_generated_at
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
