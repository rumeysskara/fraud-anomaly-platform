PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: install lint format test profile features score pipeline index rag-index api

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

pipeline:
	$(PY) scripts/run_pipeline.py

index:
	$(PY) scripts/run_pipeline.py --only index

rag-index:
	$(PY) scripts/build_rag_index.py

api:
	$(PY) -m uvicorn src.api.main:app --reload
