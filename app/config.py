"""Server-side configuration. Contract 3.2: context never comes from the client."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
STATIC_DIR = ROOT_DIR / "static"

# Fixed demo user. Never taken from the request body (no IDOR by design).
# Never call datetime.now(): always use as_of_date so results are reproducible.
CONTEXT = {"user": "arne.goossens", "country": "BE", "as_of_date": "2026-09-30"}

MAX_QUESTION_CHARS = 500
RETRIEVE_K = 6

DEBUG = os.getenv("APP_DEBUG", "false").lower() == "true"

ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
