from flask import Blueprint, request, jsonify, send_from_directory
import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import psycopg2
import psycopg2.extras

from common.auth import requires_auth
from common.db import get_db_connection
from features.register_feedback.parsers import parse_feedback_received_dt

bp = Blueprint("register_feedback", __name__)

@bp.route("/register-feedback", methods=["GET"])
@requires_auth
def serve_register_feedback():
    return send_from_directory("templates", "register_feedback.html")




@bp.route('/kpi-submit', methods=['POST'])
@requires_auth
def kpi_submit():
    payload = request.json or {}

    # ---- Link key (required) ----
    register_id = (payload.get("register_id") or "").strip()
    if not register_id:
        return jsonify({"error": "register_id is required"}), 400

    # ---- Optional vessel meta ----
    vessel_name = (payload.get("vessel_name") or "").strip() or None
    imo_no_raw = payload.get("imo_no")
    try:
        imo_no = int(imo_no_raw) if imo_no_raw not in (None, "", []) else None
    except Exception:
        imo_no = None

    # ---- Received timestamp (optional: sent from register_feedback) ----
    feedback_received_raw = (payload.get("feedback_received_raw") or payload.get("feedback_received_dt") or "").strip() or None
    feedback_received_norm = (payload.get("feedback_received_dt") or "").strip() or None

    feedback_received_at = None
    if feedback_received_norm:
        try:
            dt_naive = datetime.strptime(feedback_received_norm, "%Y-%m-%d-%H-%M")
            feedback_received_at = dt_naive.replace(tzinfo=ZoneInfo("Europe/Copenhagen"))
        except ValueError:
            return jsonify({"error": "feedback_received_dt must match YYYY-MM-DD-HH-MM"}), 400

    # ---- Action taken (optional: sent from feedback_report_generator) ----
    action_taken_code_raw = (payload.get("action_taken_code") or "").strip()
    action_taken_code = int(action_taken_code_raw) if action_taken_code_raw.isdigit() else None

    code_to_label = {
        1: "Recommendation satisfied",
        2: "Unchanged",
        3: "Recommendation not satisfied"
    }
    action_taken_label = code_to_label.get(action_taken_code) if action_taken_code is not None else None

    # Must provide at least one update payload
    if (feedback_received_at is None and feedback_received_raw is None and action_taken_code is None and vessel_name is None and imo_no is None):
        return jsonify({"error": "Nothing to update"}), 400

    # We keep your existing feedback_id column for compatibility:
    # - On first insert we generate one
    # - On update we keep the existing value
    new_feedback_id = str(uuid.uuid4())

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO public.kpi_data (
                register_id,
                vessel_name,
                imo_no,
                feedback_id,
                feedback_received_at,
                feedback_received_raw,
                action_taken_code,
                action_taken_label,
                report_generated_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s, CASE WHEN %s THEN NOW() ELSE NULL END)
            ON CONFLICT (register_id) DO UPDATE SET
                vessel_name = COALESCE(EXCLUDED.vessel_name, public.kpi_data.vessel_name),
                imo_no = COALESCE(EXCLUDED.imo_no, public.kpi_data.imo_no),
                feedback_received_at = COALESCE(EXCLUDED.feedback_received_at, public.kpi_data.feedback_received_at),
                feedback_received_raw = COALESCE(EXCLUDED.feedback_received_raw, public.kpi_data.feedback_received_raw),
                action_taken_code = COALESCE(EXCLUDED.action_taken_code, public.kpi_data.action_taken_code),
                action_taken_label = COALESCE(EXCLUDED.action_taken_label, public.kpi_data.action_taken_label),
                report_generated_at = CASE
                    WHEN %s THEN NOW()
                    ELSE public.kpi_data.report_generated_at
                END
            RETURNING id, created_at, feedback_id, feedback_received_at, report_generated_at
        """, (
            register_id,
            vessel_name,
            imo_no,
            new_feedback_id,
            feedback_received_at,
            feedback_received_raw,
            action_taken_code,
            action_taken_label,
            action_taken_code is not None,
            action_taken_code is not None
        ))

        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "ok": True,
            "id": str(row[0]),
            "created_at": row[1].isoformat() if row[1] else None,
            "feedback_id": str(row[2]) if row[2] else None,
            "feedback_received_at": row[3].isoformat() if row[3] else None,
            "report_generated_at": row[4].isoformat() if row[4] else None,
            "register_id": register_id
        })

    except Exception as e:
        print("KPI DB ERROR:", e)
        return jsonify({"error": str(e)}), 500

@bp.route('/register-feedback-submit', methods=['POST'])
@requires_auth
def register_feedback_submit():
    payload = request.json or {}

    from datetime import datetime

    def to_float(val):
        try:
            if val is None or val == "":
                return None
            return float(val)
        except (TypeError, ValueError):
            return None

    def to_float_list(lst):
        if not lst:
            return None
        return [to_float(x) for x in lst]

    def to_date(val):
        """Parse common date formats to a date object.

        Accepts:
          - YYYY-MM-DD
          - DD-MM-YYYY
          - DD/MM/YYYY
          - YYYY/MM/DD
          - ISO strings with time (YYYY-MM-DDTHH:MM:SS)
        """
        if not val:
            return None
        s = str(val).strip()
        if not s:
            return None
        # remove time part if present
        s = s.split("T")[0].strip()
        # normalize multiple spaces
        s = " ".join(s.split())

        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"
            "%d-%b-%y"
            "%d-%b-%Y"
            "%d %b %y"
            "%d %b %Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
        return None

    def to_date_flexible(val):
        """Parse date input into a python date using the same logic everywhere.

        Supports:
          - ISO date/time strings (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
          - DD-MM-YYYY, DD/MM/YYYY, DD.MM.YYYY (and 2-digit year variants)
          - YYYY/MM/DD, YYYY.MM.DD
          - Excel serial dates as numbers OR numeric strings (e.g., 45345)
        """
        if val is None or val == "":
            return None

        # Excel serial date handling (number or numeric string)
        try:
            n = None
            if isinstance(val, str) and val.strip().isdigit():
                n = float(val.strip())
            elif isinstance(val, (int, float)):
                n = float(val)
            if n is not None and n > 20000:
                base = datetime(1899, 12, 30)  # Excel (Windows) base
                return (base + timedelta(days=n)).date()
        except Exception:
            pass

        s = str(val).strip()
        # Remove time part if present
        s = s.split("T")[0].strip()
        s = s.split(" ")[0].strip()  # handles 'YYYY-MM-DD HH:MM:SS'

        for fmt in (
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%d.%m.%Y",
            "%Y/%m/%d",
            "%Y.%m.%d",            "%d-%m-%y",
            "%d/%m/%y",
            "%d.%m.%y",
        ):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass

        return None
    def any_nonempty(lst):
        return any(x not in (None, "", []) for x in (lst or []))

    def row_has_feedback(r: dict) -> bool:
        """Prevent inserting a null/empty feedback row."""
        if not isinstance(r, dict):
            return False

        # any scalar field filled?
        scalar_keys = [
            "fb_date", "me_load", "me_rpm", "avg_me_power", "daily_cyl_oil_cons",
            "cyl_oil_feed_rate", "acc_factor", "fuel_type", "fuel_sulph", "humidity",
            "tbn_fed", "pc_inlet", "pc_outlet", "amb_temp", "tbn_scraped",
            "me_lo_desludge", "me_lo_temp", "me_rh"
        ]
        for k in scalar_keys:
            v = r.get(k)
            if v not in (None, "", []):
                return True

        per = r.get("per_cylinder") or {}
        # any per-cylinder lists filled?
        for k in ("fe_mag", "fe_cor", "fe_tot", "res_tbn", "unit", "unit_val"):
            if any_nonempty(per.get(k)):
                return True

        return False

    # ----------------------------
    # Section selection (from UI)
    # ----------------------------
    selected_sections = payload.get("selected_sections")
    if not isinstance(selected_sections, list) or not selected_sections:
        # backward compatible default: behave like old UI (assume both possible)
        selected_sections = ["feedback_report", "scavenge_inspection"]

    include_feedback = "feedback_report" in selected_sections
    include_scavenge = "scavenge_inspection" in selected_sections


    # ME system oil data is optional and controlled by whether rows contain data
    include_me_sys = ("me_sys_oil" in selected_sections) or ("me_system_oil" in selected_sections) or True
    # Shared meta
    vessel_name = payload.get("vessel_name")
    imo_no = payload.get("imo_no")
    register_id = payload.get("register_id")
    created_by = payload.get("submitted_by")

    inserted_feedback_rows = 0
    inserted_scavenge_rows = 0

    inserted_me_sys_rows = 0
    inserted_lab_rows = 0
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # ----------------------------
        # Feedback report -> feedback_data (bulk rows)
        # ----------------------------
        if include_feedback:
            feedback_rows = payload.get("feedback_rows")
            if not isinstance(feedback_rows, list):
                feedback_rows = []

            # Fallback to single-row mode only if it actually contains data
            if not feedback_rows and row_has_feedback(payload):
                feedback_rows = [payload]

            insert_sql = """
                INSERT INTO public.feedback_data (
                    vessel_name,
                    imo_no,
                    register_id,
                    created_by,
                    fb_date,
                    me_load,
                    me_rpm,
                    avg_me_power,
                    daily_cyl_oil_cons,
                    cyl_oil_feed_rate,
                    acc_factor,
                    fuel_type,
                    fuel_sulph,
                    humidity,
                    tbn_fed,
                    pc_inlet,
                    pc_outlet,
                    amb_temp,
                    tbn_scraped,
                    me_lo_desludge,
                    me_lo_temp,
                    me_rh,
                    fe_mag,
                    fe_cor,
                    fe_tot,
                    res_tbn,
                    unit_val,
                    raw_payload
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s
                )
            """

            for r in feedback_rows:
                if not row_has_feedback(r):
                    continue

                per = r.get("per_cylinder") or {}

                fe_mag = to_float_list(per.get("fe_mag"))
                fe_cor = to_float_list(per.get("fe_cor"))
                fe_tot = to_float_list(per.get("fe_tot"))
                res_tbn = to_float_list(per.get("res_tbn"))
                unit_val = to_float_list(per.get("unit")) or to_float_list(per.get("unit_val"))

                fb_date = to_date_flexible(r.get("fb_date") or r.get("fbDate") or payload.get("fb_date"))

                raw_for_row = {
                    "meta": {
                        "vessel_name": vessel_name,
                        "imo_no": imo_no,
                        "register_id": register_id,
                        "submitted_by": created_by
                    },
                    "row": r
                }

                cur.execute(insert_sql, (
                    vessel_name,
                    imo_no,
                    register_id,
                    created_by,
                    fb_date,
                    to_float(r.get("me_load")),
                    to_float(r.get("me_rpm")),
                    to_float(r.get("avg_me_power")),
                    to_float(r.get("daily_cyl_oil_cons")),
                    to_float(r.get("cyl_oil_feed_rate")),
                    to_float(r.get("acc_factor")),
                    r.get("fuel_type"),
                    to_float(r.get("fuel_sulph")),
                    to_float(r.get("humidity")),
                    to_float(r.get("tbn_fed")),
                    to_float(r.get("pc_inlet")),
                    to_float(r.get("pc_outlet")),
                    to_float(r.get("amb_temp")),
                    to_float(r.get("tbn_scraped")),
                    to_float(r.get("me_lo_desludge")),
                    to_float(r.get("me_lo_temp")),
                    to_float(r.get("me_rh")),
                    fe_mag,
                    fe_cor,
                    fe_tot,
                    res_tbn,
                    unit_val,
                    psycopg2.extras.Json(raw_for_row)
                ))

                inserted_feedback_rows += 1

        
        # ----------------------------
        # Scavenge inspection -> scavenge_data (bulk rows)
        # ----------------------------
        if include_scavenge:
            scavenge_rows = payload.get("scavenge_rows")
            if not isinstance(scavenge_rows, list):
                scavenge_rows = []

            # Fallback to "single row from visible inputs" if user didn't parse/paste rows
            if not scavenge_rows:
                per = payload.get("per_cylinder") or {}
                rings_fb = (per.get("rings") or {})
                scavenge_rows = [{
                    "scav_date": payload.get("scav_date"),
                    "coat_type": payload.get("coat_type"),
                    "rings": {
                        "pr1": rings_fb.get("pr1"),
                        "pr2": rings_fb.get("pr2"),
                        "pr3": rings_fb.get("pr3"),
                        "pr4": rings_fb.get("pr4"),
                    },
                    "unit": per.get("scav_unit"),
                    "scav_mfrh": payload.get("scav_mfrh"),
                }]

            insert_scav_sql = """
                INSERT INTO public.scavenge_data (
                    register_id,
                    vessel_name,
                    imo_no,
                    created_by,
                    scav_date,
                    coat_type,
                    pr1_thickness,
                    pr2_thickness,
                    pr3_thickness,
                    pr4_thickness,
                    cyl_hours,
                    me_rh,
                    raw_payload
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """

            for r in (scavenge_rows or []):
                if not isinstance(r, dict):
                    continue

                scav_date = to_date_flexible(r.get("scav_date") or payload.get("scav_date"))
                coat_type = (r.get("coat_type") or payload.get("coat_type") or "").strip() or None

                rings = r.get("rings") or {}
                pr1 = rings.get("pr1")
                pr2 = rings.get("pr2")
                pr3 = rings.get("pr3")
                pr4 = rings.get("pr4")

                cyl_hours = r.get("unit")

                pr1 = to_float_list(pr1) if isinstance(pr1, list) else None
                pr2 = to_float_list(pr2) if isinstance(pr2, list) else None
                pr3 = to_float_list(pr3) if isinstance(pr3, list) else None
                pr4 = to_float_list(pr4) if isinstance(pr4, list) else None
                cyl_hours = to_float_list(cyl_hours) if isinstance(cyl_hours, list) else None

                scav_mfrh = to_float(r.get("scav_mfrh") or payload.get("scav_mfrh"))

                has_scavenge_payload = any([
                    scav_date is not None,
                    coat_type is not None,
                    any_nonempty(pr1), any_nonempty(pr2), any_nonempty(pr3), any_nonempty(pr4),
                    any_nonempty(cyl_hours),
                    scav_mfrh is not None
                ])

                if not has_scavenge_payload:
                    continue
                cur.execute(insert_scav_sql, (
                    register_id,
                    vessel_name,
                    imo_no,
                    created_by,
                    scav_date,
                    coat_type,
                    pr1,
                    pr2,
                    pr3,
                    pr4,
                    cyl_hours,
                    scav_mfrh,
                    psycopg2.extras.Json({
                        "meta": {
                            "vessel_name": vessel_name,
                            "imo_no": imo_no,
                            "register_id": register_id,
                            "submitted_by": created_by
                        },
                        "row": r
                    })
                ))

                inserted_scavenge_rows += 1

        # ----------------------------
        # ME system oil -> me_sys_data (bulk rows)
        # ----------------------------
        if include_me_sys:
            me_sys_rows = payload.get("me_sys_rows")
            if not isinstance(me_sys_rows, list):
                me_sys_rows = []

            def row_has_me_sys(rr: dict) -> bool:
                if not isinstance(rr, dict):
                    return False
                keys = [
                    "sys_date","visc40","visc100","base_number","topup_volume","vanadium",
                    "pq_index","oil_on_label","iso_code","pc4","pc6","pc14"
                ]
                return any((rr.get(k) not in (None, "", [])) for k in keys)

            # Fallback: if user didn't add rows, use the visible inputs (single row)
            if not me_sys_rows and row_has_me_sys(payload):
                me_sys_rows = [payload]

            insert_sys_sql = """
                INSERT INTO public.me_sys_data (
                    register_id,
                    vessel_name,
                    imo_no,
                    created_by,
                    sys_date,
                    visc40,
                    visc100,
                    base_number,
                    topup_volume,
                    vanadium,
                    pq_index,
                    oil_on_label,
                    iso_code,
                    pc4,
                    pc6,
                    pc14,
                    raw_payload
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """

            for r in (me_sys_rows or []):
                if not isinstance(r, dict) or not row_has_me_sys(r):
                    continue

                sys_date = to_date_flexible(r.get("sys_date") or r.get("date") or payload.get("sys_date"))

                cur.execute(insert_sys_sql, (
                    register_id,
                    vessel_name,
                    imo_no,
                    created_by,
                    sys_date,
                    to_float(r.get("visc40")),
                    to_float(r.get("visc100")),
                    to_float(r.get("base_number")),
                    to_float(r.get("topup_volume")),
                    to_float(r.get("vanadium")),
                    to_float(r.get("pq_index")),
                    (r.get("oil_on_label") or "").strip() or None,
                    (r.get("iso_code") or "").strip() or None,
                    to_float(r.get("pc4")),
                    to_float(r.get("pc6")),
                    to_float(r.get("pc14")),
                    psycopg2.extras.Json({
                        "meta": {
                            "vessel_name": vessel_name,
                            "imo_no": imo_no,
                            "register_id": register_id,
                            "submitted_by": created_by
                        },
                        "row": r
                    })
                ))

                inserted_me_sys_rows += 1


        # ----------------------------
        # Laboratory scrapedown report -> scrape_lab (single date)
        # ----------------------------
        lab_date = to_date_flexible(payload.get("lab_scrapedown_date") or payload.get("lab_date"))
        if lab_date is not None:
            insert_lab_sql = """
                INSERT INTO public.scrape_lab (
                    register_id,
                    vessel_name,
                    imo_no,
                    created_by,
                    lab_date,
                    raw_payload
                )
                VALUES (%s,%s,%s,%s,%s,%s)
            """
            cur.execute(insert_lab_sql, (
                register_id,
                vessel_name,
                imo_no,
                created_by,
                lab_date,
                psycopg2.extras.Json({
                    "meta": {
                        "vessel_name": vessel_name,
                        "imo_no": imo_no,
                        "register_id": register_id,
                        "submitted_by": created_by
                    },
                    "lab_scrapedown_date_raw": payload.get("lab_scrapedown_date"),
                    "payload": payload
                })
            ))
            inserted_lab_rows += 1

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "ok": True,
            "inserted_feedback_rows": inserted_feedback_rows,
            "inserted_scavenge_rows": inserted_scavenge_rows,
            "inserted_me_sys_rows": inserted_me_sys_rows,
            "inserted_lab_rows": inserted_lab_rows
        })

    except Exception as e:
        print("DB ERROR:", e)
        return jsonify({"error": str(e)}), 500



@bp.route('/withdraw-feedback', methods=['POST'])
@requires_auth
def withdraw_feedback():
    data = request.json or {}
    register_id = data.get("register_id")
    deleted_by = data.get("deleted_by")

    if not register_id:
        return jsonify({"error": "register_id required"}), 400
    if not deleted_by:
        return jsonify({"error": "deleted_by required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            update public.feedback_data
            set is_deleted = true,
                deleted_at = now(),
                deleted_by = %s
            where register_id = %s
        """, (deleted_by, register_id))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"ok": True})

    except Exception as e:
        print("Withdraw error:", e)
        return jsonify({"error": str(e)}), 500

   

@bp.route('/feedback-list')
@requires_auth
def feedback_list():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            select created_by,
                vessel_name,
                register_id,
                fb_date,
                created_at
            from (
                select distinct on (register_id)
                    created_by,
                    vessel_name,
                    register_id,
                    fb_date,
                    created_at
                from public.feedback_data
                where is_deleted = false
                order by register_id, created_at desc
            ) t
            order by created_at desc
            limit 30
        """)

        rows = cur.fetchall()
        cur.close()
        conn.close()

        result = []
        for r in rows:
            result.append({
                "created_by": r[0],
                "vessel_name": r[1],
                "register_id": r[2],
                "fb_date": r[3].isoformat() if r[3] else None,
                "created_at": r[4].isoformat()
            })

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ----------------------------
# Unified submissions list (feedback + scavenge)
# ----------------------------

@bp.route('/submission-list')
@requires_auth
def submission_list():
    """Latest 30 submissions across feedback_data + scavenge_data (excluding deleted)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            with fb as (
                select distinct on (register_id)
                    created_by,
                    vessel_name,
                    register_id,
                    created_at,
                    'feedback'::text as submission_type
                from public.feedback_data
                where is_deleted = false
                order by register_id, created_at desc
            ),
            sc as (
                select distinct on (register_id)
                    created_by,
                    vessel_name,
                    register_id,
                    created_at,
                    'scavenge'::text as submission_type
                from public.scavenge_data
                where is_deleted = false
                order by register_id, created_at desc
            ),
            ms as (
                select distinct on (register_id)
                    created_by,
                    vessel_name,
                    register_id,
                    created_at,
                    'me sys oil'::text as submission_type
                from public.me_sys_data
                where is_deleted = false
                order by register_id, created_at desc
            ),
            lb as (
                select distinct on (register_id)
                    created_by,
                    vessel_name,
                    register_id,
                    created_at,
                    'lab scrapedown'::text as submission_type
                from public.scrape_lab
                where is_deleted = false
                order by register_id, created_at desc
            )
            select * from (
                select * from fb
                union all
                select * from sc
                union all
                select * from ms
                union all
                select * from lb
            ) u
            order by created_at desc
            limit 30
        """)

        rows = cur.fetchall()
        cur.close()
        conn.close()

        result = []
        for r in rows:
            result.append({
                "created_by": r[0],
                "vessel_name": r[1],
                "register_id": r[2],
                "created_at": r[3].isoformat(),
                "submission_type": r[4]
            })

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500



@bp.route('/withdraw-submission', methods=['POST'])
@requires_auth
def withdraw_submission():
    data = request.json or {}
    register_id = data.get("register_id")
    deleted_by = data.get("deleted_by")
    submission_type = (data.get("submission_type") or "").strip().lower()

    if not register_id:
        return jsonify({"error": "register_id required"}), 400
    if not deleted_by:
        return jsonify({"error": "deleted_by required"}), 400
    if submission_type not in ("feedback", "scavenge", "me sys oil", "me_sys_oil", "lab scrapedown", "lab_scrapedown"):
        return jsonify({"error": "submission_type must be 'feedback', 'scavenge', 'me sys oil' or 'lab scrapedown'"}), 400

    # normalize
    if submission_type == "me_sys_oil":
        submission_type = "me sys oil"
    if submission_type == "lab_scrapedown":
        submission_type = "lab scrapedown"

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if submission_type == "feedback":
            cur.execute("""
                update public.feedback_data
                set is_deleted = true,
                    deleted_at = now(),
                    deleted_by = %s
                where register_id = %s
            """, (deleted_by, register_id))
                # soft-delete KPI row for same register_id
            cur.execute("""
                update public.kpi_data
                set is_deleted = true,
                    deleted_at = now(),
                    deleted_by = %s
                where register_id = %s
            """, (deleted_by, register_id))
        elif submission_type == "scavenge":
            cur.execute("""
                update public.scavenge_data
                set is_deleted = true,
                    deleted_at = now(),
                    deleted_by = %s
                where register_id = %s
            """, (deleted_by, register_id))
        elif submission_type == "lab scrapedown":
            cur.execute("""
                update public.scrape_lab
                set is_deleted = true,
                    deleted_at = now(),
                    deleted_by = %s
                where register_id = %s
            """, (deleted_by, register_id))
        else:
            cur.execute("""
                update public.me_sys_data
                set is_deleted = true,
                    deleted_at = now(),
                    deleted_by = %s
                where register_id = %s
            """, (deleted_by, register_id))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"ok": True})

    except Exception as e:
        print("Withdraw submission error:", e)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)