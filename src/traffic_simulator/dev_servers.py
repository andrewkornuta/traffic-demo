from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    base_dir = Path(__file__).resolve().parents[2]
    api_cmd = [sys.executable, "-m", "uvicorn", "traffic_simulator.api:app", "--reload"]
    streamlit_cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(base_dir / "src/traffic_simulator/streamlit_app.py"),
        "--server.port",
        "8501",
    ]
    api = subprocess.Popen(api_cmd, cwd=base_dir)
    time.sleep(1)
    streamlit = subprocess.Popen(streamlit_cmd, cwd=base_dir)
    try:
        api.wait()
        streamlit.wait()
    except KeyboardInterrupt:
        api.terminate()
        streamlit.terminate()


if __name__ == "__main__":
    main()
