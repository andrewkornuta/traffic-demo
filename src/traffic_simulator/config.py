from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = BASE_DIR / "artifacts"
DEFAULT_DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'traffic_simulator.db'}")
API_URL = os.getenv("TRAFFIC_API_URL", "http://127.0.0.1:8000")

ARTIFACTS_DIR.mkdir(exist_ok=True)

