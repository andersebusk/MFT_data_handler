Refactored Flask app structure (Blueprint-based)

Run locally:
  export FLASK_APP=app.py
  flask run

Render start command suggestion:
  gunicorn app:app

Notes:
- Templates live in ./templates
- Feature routes are under ./features
- Shared helpers under ./common
