"""
Tests for the FastAPI layer.
Runs against a live uvicorn process — start it before running:
    uvicorn api.main:app --port 8000 &
"""
import pytest
import requests

BASE = "http://localhost:8000"
HEADERS = {"X-API-Key": "dev-key"}


@pytest.fixture(scope="module")
def api():
    """Verify the API is reachable before running any test."""
    try:
        r = requests.get(f"{BASE}/health", headers=HEADERS, timeout=5)
        r.raise_for_status()
    except Exception as exc:
        pytest.skip(f"API not reachable: {exc}")


class TestHealth:
    def test_health_ok(self, api):
        r = requests.get(f"{BASE}/health", headers=HEADERS, timeout=5)
        assert r.status_code == 200

    def test_unauthorized_rejected(self, api):
        r = requests.get(f"{BASE}/metrics", timeout=5)
        assert r.status_code == 401


class TestMetrics:
    def test_metrics_returns_200(self, api):
        r = requests.get(f"{BASE}/metrics", headers=HEADERS, timeout=10)
        assert r.status_code == 200

    def test_metrics_has_regions(self, api):
        data = requests.get(f"{BASE}/metrics", headers=HEADERS, timeout=10).json()
        assert "regions" in data
        assert len(data["regions"]) > 0

    def test_data_summary_returns_200(self, api):
        r = requests.get(f"{BASE}/data/summary", headers=HEADERS, timeout=10)
        assert r.status_code == 200

    def test_data_summary_has_monthly(self, api):
        data = requests.get(f"{BASE}/data/summary", headers=HEADERS, timeout=10).json()
        assert "monthly" in data
        assert len(data["monthly"]) > 0


class TestInsights:
    def test_local_insights_returns_200(self, api):
        r = requests.post(
            f"{BASE}/insights",
            json={"question": "test", "force_local": True},
            headers=HEADERS, timeout=30,
        )
        assert r.status_code == 200

    def test_local_insights_has_insight_field(self, api):
        data = requests.post(
            f"{BASE}/insights",
            json={"question": "Which category is growing fastest?", "force_local": True},
            headers=HEADERS, timeout=30,
        ).json()
        assert "insight" in data
        assert data["llm_used"] is False

    def test_exec_brief_returns_200(self, api):
        r = requests.post(
            f"{BASE}/insights/exec",
            json={"question": "Which regions are underperforming?"},
            headers=HEADERS, timeout=30,
        )
        assert r.status_code == 200

    def test_exec_brief_structure(self, api):
        data = requests.post(
            f"{BASE}/insights/exec",
            json={"question": "Which regions are underperforming?"},
            headers=HEADERS, timeout=30,
        ).json()
        assert "narrative" in data
        assert "evidence" in data
        assert "sources" in data
        assert isinstance(data["narrative"], str)
        assert len(data["narrative"]) > 20


class TestPredict:
    def test_predict_returns_200(self, api):
        r = requests.post(
            f"{BASE}/predict",
            json={
                "category": "Beverages", "region": "North",
                "year": 2026, "month": 7,
                "avg_temp_celsius": 28.0, "rainfall_mm": 45.0,
                "marketing_spend_usd": 15000, "active_promos": 3,
                "avg_discount_pct": 5.0,
            },
            headers=HEADERS, timeout=15,
        )
        assert r.status_code == 200

    def test_predict_returns_positive_revenue(self, api):
        data = requests.post(
            f"{BASE}/predict",
            json={
                "category": "Snacks", "region": "South",
                "year": 2026, "month": 3,
                "avg_temp_celsius": 22.0, "rainfall_mm": 60.0,
                "marketing_spend_usd": 12000, "active_promos": 2,
                "avg_discount_pct": 4.0,
            },
            headers=HEADERS, timeout=15,
        ).json()
        assert data["predicted_revenue"] > 0
