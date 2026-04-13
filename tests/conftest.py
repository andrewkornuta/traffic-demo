from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def reset_state():
    from traffic_simulator.config import ARTIFACTS_DIR
    from traffic_simulator.db import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    if ARTIFACTS_DIR.exists():
        shutil.rmtree(ARTIFACTS_DIR)
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    yield

