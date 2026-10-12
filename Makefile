PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: install lint format test profile features score context rules pipeline rag-index agents-demo api

install:
	$(PY) -m pip install -r requirements.txt

lint:
	$(PY) -m ruff check src tests scripts
	$(PY) -m black --check src tests scripts

format:
	$(PY) -m ruff check --fix src tests scripts
	$(PY) -m black src tests scripts

test:
	$(PY) -m pytest -q

profile:
	$(PY) scripts/run_pipeline.py --only profile

features:
	$(PY) scripts/run_pipeline.py --only features

score:
	$(PY) scripts/run_pipeline.py --only score

context:
	$(PY) scripts/run_pipeline.py --only context

rules:
	$(PY) scripts/run_pipeline.py --only rules

pipeline:
	$(PY) scripts/run_pipeline.py

rag-index:
	$(PY) scripts/build_rag_index.py

agents-demo:
	$(PY) scripts/run_agents_demo.py

api:
	$(PY) -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
