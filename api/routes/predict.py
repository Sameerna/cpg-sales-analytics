
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ml.predict import predict as ml_predict

router = APIRouter(prefix="/predict", tags=["predict"])


class PredictRequest(BaseModel):
    category: str = Field(..., example="Beverages")
    region: str = Field(..., example="North")
    year: int = Field(..., example=2024)
    month: int = Field(..., ge=1, le=12, example=6)
    avg_temp_celsius: float = Field(15.0, example=18.0)
    rainfall_mm: float = Field(50.0, example=40.0)
    marketing_spend_usd: float = Field(5000.0, example=7500.0)
    active_promos: int = Field(2, ge=0, example=3)
    avg_discount_pct: float = Field(10.0, ge=0.0, le=100.0, example=12.5)


class PredictResponse(BaseModel):
    category: str
    region: str
    year: int
    month: int
    predicted_revenue: float


@router.post("", response_model=PredictResponse)
def predict(body: PredictRequest) -> PredictResponse:
    try:
        result = ml_predict(
            category=body.category,
            region=body.region,
            year=body.year,
            month=body.month,
            avg_temp_celsius=body.avg_temp_celsius,
            rainfall_mm=body.rainfall_mm,
            marketing_spend_usd=body.marketing_spend_usd,
            active_promos=body.active_promos,
            avg_discount_pct=body.avg_discount_pct,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return PredictResponse(**result)
