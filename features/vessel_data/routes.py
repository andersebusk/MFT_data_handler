from flask import Blueprint, render_template, jsonify, request
import os
import psycopg2
import psycopg2.extras

vessel_data_bp = Blueprint("vessel_data", __name__)

DISPLAY_COLUMNS = [
    "created_at",
    "vessel_name",
    "imo_no",
    "register_id",
    "fb_date",
    "me_load",
    "me_rpm",
    "avg_me_power",
    "daily_cyl_oil_cons",
    "cyl_oil_feed_rate",
    "acc_factor",
    "fuel_type",
    "fuel_sulph",
    "humidity",
    "tbn_fed",
    "pc_inlet",
    "pc_outlet",
    "amb_temp",
    "tbn_scraped",
    "me_lo_desludge",
    "me_lo_temp",
    "me_rh",
    "fe_mag",
    "fe_cor",
    "fe_tot",
    "res_tbn",
    "unit_val",
    "is_deleted",
    "deleted_at",
    "deleted_by",
    "created_by",
]

# Rename headers to match register_feedback wording where possible
HEADER_LABELS = {
    "created_at": "Created at",
    "vessel_name": "Vessel Name",
    "imo_no": "IMO Number",
    "register_id": "Register ID",
    "fb_date": "Date",
    "me_load": "Main Engine load [%]",
    "me_rpm": "Main Engine RPM [rpm]",
    "avg_me_power": "Average Main Engine power [kWh]",
    "daily_cyl_oil_cons": "Daily Cylinder Oil Consumption [ltrs]",
    "cyl_oil_feed_rate": "Cylinder oil Feed rate [g/kWh]",
    "acc_factor": "Cylinder Lubricator ACC factor [% m/m]",
    "fuel_type": "Fuel type",
    "fuel_sulph": "Fuel sulphur content [%]",
    "humidity": "Humidity [%]",
    "tbn_fed": "TBN of blended oil fed to engine [BN]",
    "pc_inlet": "ME PC oil Temp Avg INLET [C degr.]",
    "pc_outlet": "ME PC oil Temp Avg OUTLET [C degr.]",
    "amb_temp": "Ambient engine room temperature [C degr.]",
    "tbn_scraped": "TBN scraped down [BN]",
    "me_lo_desludge": "ME LO purifier desludging intervals [hrs]",
    "me_lo_temp": "ME LO purification temperature [C degr.]",
    "me_rh": "ME RH [hrs]",
    "fe_mag": "Fe magnetic [ppm]",
    "fe_cor": "Fe corrosive [ppm]",
    "fe_tot": "Fe total [ppm]",
    "res_tbn": "Residual TBN [BN]",
    "unit_val": "Cylinder RH [hrs]",
    "is_deleted": "Deleted",
    "deleted_at": "Deleted at",
    "deleted_by": "Deleted by",
    "created_by": "Created by",
}

def get_db_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(database_url, sslmode="require")


@vessel_data_bp.route("/vessel-data", methods=["GET"])
def vessel_data_page():
    return render_template("vessel_data.html")


@vessel_data_bp.route("/api/vessel-data/vessels", methods=["GET"])
def get_vessels():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT DISTINCT vessel_name
            FROM legacy_vessels
            WHERE vessel_name IS NOT NULL
              AND TRIM(vessel_name) <> ''
            ORDER BY vessel_name ASC
        """)
        vessels = [row[0] for row in cur.fetchall()]
        return jsonify(vessels)
    finally:
        cur.close()
        conn.close()


@vessel_data_bp.route("/api/vessel-data/data", methods=["POST"])
def get_vessel_data():
    payload = request.get_json(silent=True) or {}
    selected_vessels = payload.get("vessels", [])

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        sql = f"""
            SELECT {", ".join(DISPLAY_COLUMNS)}
            FROM feedback_data
        """
        params = []

        if selected_vessels:
            sql += " WHERE vessel_name = ANY(%s)"
            params.append(selected_vessels)

        sql += """
            ORDER BY vessel_name ASC,
                     fb_date DESC NULLS LAST,
                     created_at DESC NULLS LAST
        """

        cur.execute(sql, params)
        rows = cur.fetchall()

        return jsonify({
            "columns": DISPLAY_COLUMNS,
            "header_labels": HEADER_LABELS,
            "rows": rows
        })
    finally:
        cur.close()
        conn.close()