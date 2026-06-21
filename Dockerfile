FROM python:3.9-slim

WORKDIR /app

# System deps needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Build the database and ML artefact at image build time
RUN python3 ingestion/load_raw.py \
    && python3 ingestion/validate.py \
    && dbt run --project-dir dbt_project --profiles-dir dbt_project \
    && python3 ml/train.py

# Expose API and dashboard ports
EXPOSE 8000 8501

# Default: start the API. Override CMD in docker-compose for the dashboard.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
