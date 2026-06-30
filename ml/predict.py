"""
Inference module used by the FastAPI layer.
Loads the saved Ridge pipeline and returns a revenue prediction.
"""
import os
import pickle
from pathlib import Path

import pandas as pd

MODEL_PATH = Path(os.getenv("MODEL_PATH", "./ml/models/model.pkl"))

_pipeline = None


def _load_pipeline():
    global _pipeline
    if _pipeline is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Model not found at {MODEL_PATH}. Run `python3 ml/train.py` first."
            )
        with open(MODEL_PATH, "rb") as f:
            _pipeline = pickle.load(f)
    return _pipeline


def predict(
    category: str,
    region: str,
    year: int,
    month: int,
    avg_temp_celsius: float = 15.0,
    rainfall_mm: float = 50.0,
    marketing_spend_usd: float = 5000.0,
    active_promos: int = 2,
    avg_discount_pct: float = 10.0,
) -> dict:
    """Return predicted monthly revenue and input echo."""
    pipeline = _load_pipeline()

    row = pd.DataFrame([{
        "category":            category,
        "region":              region,
        "month_num":           month,
        "year_num":            year,
        "avg_temp_celsius":    avg_temp_celsius,
        "rainfall_mm":         rainfall_mm,
        "marketing_spend_usd": marketing_spend_usd,
        "active_promos":       active_promos,
        "avg_discount_pct":    avg_discount_pct,
    }])

    predicted_revenue = float(pipeline.predict(row)[0])

    return {
        "category":         category,
        "region":           region,
        "year":             year,
        "month":            month,
        "predicted_revenue": round(predicted_revenue, 2),
    }
