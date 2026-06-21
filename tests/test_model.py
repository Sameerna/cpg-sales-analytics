"""
Tests for the ML model — verifies the saved artefact loads and predicts correctly.
"""
import pytest


@pytest.fixture(scope="module")
def predictor():
    try:
        from ml.predict import predict
        return predict
    except Exception as exc:
        pytest.skip(f"ml.predict not importable: {exc}")


class TestModelLoads:
    def test_predict_function_callable(self, predictor):
        assert callable(predictor)

    def test_returns_dict_with_predicted_revenue(self, predictor):
        result = predictor(
            category="Beverages", region="North",
            year=2026, month=6,
            avg_temp_celsius=25.0, rainfall_mm=50.0,
            marketing_spend_usd=14000, active_promos=2,
            avg_discount_pct=4.5,
        )
        assert "predicted_revenue" in result
        assert isinstance(result["predicted_revenue"], (int, float))

    def test_prediction_is_positive(self, predictor):
        result = predictor(
            category="Dairy", region="East",
            year=2026, month=1,
            avg_temp_celsius=10.0, rainfall_mm=80.0,
            marketing_spend_usd=10000, active_promos=1,
            avg_discount_pct=3.0,
        )
        assert result["predicted_revenue"] > 0

    def test_higher_marketing_spend_increases_prediction(self, predictor):
        base = dict(
            category="Snacks", region="West",
            year=2026, month=4,
            avg_temp_celsius=20.0, rainfall_mm=40.0,
            active_promos=2, avg_discount_pct=5.0,
        )
        low  = predictor(**base, marketing_spend_usd=5_000)
        high = predictor(**base, marketing_spend_usd=50_000)
        assert high["predicted_revenue"] > low["predicted_revenue"], (
            "Higher marketing spend should yield higher predicted revenue"
        )

    def test_all_categories_predict(self, predictor):
        categories = ["Beverages", "Snacks", "Dairy", "Personal Care", "Household"]
        for cat in categories:
            result = predictor(
                category=cat, region="North",
                year=2026, month=6,
                avg_temp_celsius=22.0, rainfall_mm=55.0,
                marketing_spend_usd=12000, active_promos=2,
                avg_discount_pct=4.0,
            )
            assert result["predicted_revenue"] > 0, f"{cat} returned non-positive prediction"
