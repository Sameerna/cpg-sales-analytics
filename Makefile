.PHONY: venv install ingest dbt train api dashboard test test-api test-all lint docker-build docker-up docker-down

venv:
	python3 -m venv .venv
	@echo "Run: source .venv/bin/activate"

install:
	pip install -r requirements.txt

ingest:
	python3 ingestion/load_raw.py
	python3 ingestion/validate.py

dbt:
	dbt run --project-dir dbt_project --profiles-dir dbt_project

train:
	python3 ml/train.py

setup: install ingest dbt train

api:
	uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

dashboard:
	streamlit run dashboard/app.py

test:
	pytest tests/test_ingestion.py tests/test_model.py -v

test-api:
	pytest tests/test_api.py -v

test-all:
	pytest tests/ -v

lint:
	ruff check .

docker-build:
	docker build -t cpg-analytics .

docker-up:
	docker compose up -d

docker-down:
	docker compose down
