import os
from dotenv import load_dotenv

load_dotenv()

# Basic auth (HTTP Basic)
APP_USERNAME = os.environ.get("APP_USERNAME", "defaultusername")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "defaultpassword")

# PDFGenerator
PDFGENERATOR_API_KEY = os.environ.get("PDFGENERATOR_API_KEY")
PDFGENERATOR_API_SECRET = os.environ.get("PDFGENERATOR_API_SECRET")
PDFGENERATOR_WORKSPACE_IDENTIFIER = os.environ.get("PDFGENERATOR_WORKSPACE_IDENTIFIER")
PDFGENERATOR_TEMPLATE_ID = os.environ.get("PDFGENERATOR_TEMPLATE_ID")

# Database
DATABASE_URL = os.getenv("DATABASE_URL")

# Vessel master data (Excel)
VESSEL_EXCEL_FILE = os.environ.get("VESSEL_EXCEL_FILE")

# S3 for images
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
AWS_REGION = os.environ.get("AWS_REGION")
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
