PYTHON ?= python3

.PHONY: install api streamlit demo test

install:
	$(PYTHON) -m pip install --user ".[dev]"

api:
	PYTHONPATH=src $(PYTHON) -m uvicorn traffic_simulator.api:app --reload

streamlit:
	PYTHONPATH=src $(PYTHON) -m streamlit run src/traffic_simulator/streamlit_app.py

demo:
	PYTHONPATH=src $(PYTHON) -m traffic_simulator.dev_servers

test:
	PYTHONPATH=src pytest
