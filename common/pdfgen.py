import time
import jwt
import requests
from config import (
    PDFGENERATOR_API_KEY,
    PDFGENERATOR_API_SECRET,
    PDFGENERATOR_WORKSPACE_IDENTIFIER,
    PDFGENERATOR_TEMPLATE_ID,
)

def get_pdfgenerator_jwt() -> str:
    if not (PDFGENERATOR_API_KEY and PDFGENERATOR_API_SECRET and PDFGENERATOR_WORKSPACE_IDENTIFIER):
        raise RuntimeError("Missing PDFGenerator credentials in environment variables")
    payload = {
        "iss": PDFGENERATOR_API_KEY,
        "sub": PDFGENERATOR_WORKSPACE_IDENTIFIER,
        "exp": int(time.time()) + 60,
    }
    return jwt.encode(payload, PDFGENERATOR_API_SECRET, algorithm="HS256")

def generate_pdf(payload: dict) -> dict:
    token = get_pdfgenerator_jwt()
    url = "https://us1.pdfgeneratorapi.com/api/v4/documents/generate"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "template": {"id": PDFGENERATOR_TEMPLATE_ID},
        "data": payload,
        "format": "pdf",
        "output": "url",
    }
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()
