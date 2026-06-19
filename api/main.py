"""
FastAPI application entry point.
API key authentication via X-API-Key header, checked against the API_KEY env var.
"""
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

load_dotenv()

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: Optional[str] = Security(API_KEY_HEADER)) -> str:
    expected = os.getenv("API_KEY")
    if not expected:
        raise RuntimeError("API_KEY env var is not set.")
    if key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    return key


app = FastAPI(
    title="CPG Sales Analytics API",
    version="1.0.0",
    description="Revenue forecasting, KPI metrics, and privacy-safe LLM insights for CPG analytics.",
)

from api.routes import data, insights, metrics, predict  # noqa: E402

app.include_router(predict.router, dependencies=[Depends(require_api_key)])
app.include_router(metrics.router, dependencies=[Depends(require_api_key)])
app.include_router(insights.router, dependencies=[Depends(require_api_key)])
app.include_router(data.router, dependencies=[Depends(require_api_key)])


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}
