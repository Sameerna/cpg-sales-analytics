"""
Trains a Ridge regression model on mart_forecast_inputs.
Logs params, metrics and the model artefact to MLflow.
Run: python3 ml/train.py
"""
import os
import pickle
from pathlib import Path

import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer

import sqlite3

DB_PATH      = os.getenv("DB_PATH", "./data/cpg.db")
MODEL_PATH   = Path("ml/models/model.pkl")
MLFLOW_URI   = os.getenv("MLFLOW_TRACKING_URI", "./mlruns")

NUMERIC_FEATURES = [
    "month_num",
    "year_num",
    "avg_temp_celsius",
    "rainfall_mm",
    "marketing_spend_usd",
    "active_promos",
    "avg_discount_pct",
]
CATEGORICAL_FEATURES = ["category", "region"]
TARGET = "monthly_revenue"


def load_data() -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM mart_forecast_inputs", con)
    con.close()
    df["month_num"] = df["month"].astype(int)
    df["year_num"]  = df["year"].astype(int)
    return df


def build_pipeline(alpha: float = 1.0) -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
            ("num", "passthrough", NUMERIC_FEATURES),
        ]
    )
    return Pipeline([
        ("preprocessor", preprocessor),
        ("model", Ridge(alpha=alpha)),
    ])


def train() -> None:
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment("cpg_revenue_forecast")

    df = load_data()
    X = df[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    alpha = float(os.getenv("RIDGE_ALPHA", "1.0"))

    with mlflow.start_run():
        mlflow.log_param("alpha",      alpha)
        mlflow.log_param("train_rows", len(X_train))
        mlflow.log_param("test_rows",  len(X_test))
        mlflow.log_param("features",   CATEGORICAL_FEATURES + NUMERIC_FEATURES)

        pipeline = build_pipeline(alpha=alpha)
        pipeline.fit(X_train, y_train)

        y_pred = pipeline.predict(X_test)
        mae  = mean_absolute_error(y_test, y_pred)
        r2   = r2_score(y_test, y_pred)

        mlflow.log_metric("mae", round(mae, 2))
        mlflow.log_metric("r2",  round(r2,  4))
        mlflow.sklearn.log_model(pipeline, "ridge_model")

        print(f"MAE : ${mae:,.2f}")
        print(f"R²  : {r2:.4f}")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(pipeline, f)
    print(f"Model saved → {MODEL_PATH}")


if __name__ == "__main__":
    train()
