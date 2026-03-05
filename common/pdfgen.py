# pdfgen.py
import time
import jwt
import requests
from datetime import datetime

from config import (
    PDFGENERATOR_API_KEY,
    PDFGENERATOR_API_SECRET,
    PDFGENERATOR_WORKSPACE_IDENTIFIER,
    PDFGENERATOR_TEMPLATE_ID,
)

PDFGEN_URL = "https://us1.pdfgeneratorapi.com/api/v4/documents/generate"


def get_pdfgenerator_jwt() -> str:
    if not (PDFGENERATOR_API_KEY and PDFGENERATOR_API_SECRET and PDFGENERATOR_WORKSPACE_IDENTIFIER):
        raise RuntimeError("Missing PDFGenerator credentials in environment variables")

    payload = {
        "iss": PDFGENERATOR_API_KEY,
        "sub": PDFGENERATOR_WORKSPACE_IDENTIFIER,
        "exp": int(time.time()) + 60,
    }

    token = jwt.encode(payload, PDFGENERATOR_API_SECRET, algorithm="HS256")

    # PyJWT may return bytes in some versions
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def generate_pdf(user_data: dict) -> dict:
    """
    Mirrors the old working payload structure from the monolithic app:
      template: { id, data: {...} }
      format/output/name at top level
    Returns the full JSON response from PDFGeneratorAPI.
    """
    if not PDFGENERATOR_TEMPLATE_ID:
        raise RuntimeError("PDFGENERATOR_TEMPLATE_ID is not set")

    token = get_pdfgenerator_jwt()

    today_str = datetime.today().strftime("%Y-%m-%d")
    vessel_name = (user_data.get("vessel_name") or "").strip()
    safe_vessel = vessel_name.replace(" ", "_") if vessel_name else "UNKNOWN_VESSEL"

    # IMPORTANT: This matches your old working app.py payload shape :contentReference[oaicite:2]{index=2}
    body = {
        "template": {
            "id": PDFGENERATOR_TEMPLATE_ID,
            "data": {
                "customer": user_data.get("customer"),
                "C/Eng": user_data.get("C/Eng"),
                "vessel_name": user_data.get("vessel_name"),
                "date": user_data.get("date"),
                "eng_name": user_data.get("eng_name"),
                "imo_no": user_data.get("imo_no"),
                "status": user_data.get("status"),
                "en_manu": user_data.get("en_manu"),
                "en_mod": user_data.get("en_mod"),
                "mcr_out": user_data.get("mcr_out"),
                "sample_per": user_data.get("sample_per"),
                "on_sample_date": user_data.get("on_sample_date"),
                "lab_sample_date": user_data.get("lab_sample_date"),
                "avg_load": user_data.get("avg_load"),
                "fo_sulph": user_data.get("fo_sulph"),
                "fil_pur": user_data.get("fil_pur"),
                "clo_bn": user_data.get("clo_bn"),
                "clo_24hrs": user_data.get("clo_24hrs"),
                "acc_fac": user_data.get("acc_fac"),
                "feed_before": user_data.get("feed_before"),
                "feed_rep": user_data.get("feed_rep"),
                "res_bn_obs": user_data.get("res_bn_obs"),
                "fe_tot_obs": user_data.get("fe_tot_obs"),
                "feed_obs": user_data.get("feed_obs"),
                "add_com_obs": user_data.get("add_com_obs"),
                "we_suggest": user_data.get("we_suggest"),
                "add_com_sugg": user_data.get("add_com_sugg"),
                "fe_tbn_image_url": user_data.get("fe_tbn_image_url"),
                "tbn_fed_image_url": user_data.get("tbn_fed_image_url"),
                "fe_tot_load_image_url": user_data.get("fe_tot_load_image_url"),
                "feedrate_load_fe_image_url": user_data.get("feedrate_load_fe_image_url"),
            },
        },
        "format": "pdf",
        "output": "url",
        "name": f"{today_str}_BOB_Feedback_Report_{safe_vessel}",
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(PDFGEN_URL, headers=headers, json=body, timeout=60)

    # If it fails, raise a useful error (your route can catch it and return JSON)
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"PDFGeneratorAPI failed: {resp.status_code} {resp.text}") from e

    return resp.json()