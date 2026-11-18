"""API behavior tests."""

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

client = TestClient(app)


def test_health_is_public() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_is_served_from_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Risk console" in response.text


def test_dashboard_assets_are_served() -> None:
    assert client.get("/styles.css").status_code == 200
    assert client.get("/app.js").status_code == 200


def test_score_requires_api_key() -> None:
    response = client.post("/api/v1/score", json={"transaction_id": "tx-1", "amount": 10})
    assert response.status_code == 401


def test_score_returns_bounded_risk() -> None:
    response = client.post(
        "/api/v1/score",
        headers={"X-API-Key": get_settings().api_key},
        json={"transaction_id": "tx-2", "amount": 125, "currency": "USD"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["transaction_id"] == "tx-2"
    assert 0 <= payload["risk_score"] <= 1
    assert payload["decision"] in {"approve", "review"}


def test_mobile_integrity_rule_can_decline_transaction() -> None:
    response = client.post(
        "/api/v1/score",
        headers={"X-API-Key": get_settings().api_key},
        json={
            "transaction_id": "tx-mobile-1",
            "channel": "mobile",
            "amount": 125,
            "device_integrity_ok": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "decline"
    assert "mobile_device_integrity_check_failed" in payload["reasons"]


def test_card_not_present_rule_can_require_review() -> None:
    response = client.post(
        "/api/v1/score",
        headers={"X-API-Key": get_settings().api_key},
        json={
            "transaction_id": "tx-card-1",
            "channel": "card",
            "amount": 1200,
            "card_present": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "review"
    assert "card_not_present_and_high_amount" in payload["reasons"]


def test_feedback_acknowledges_label() -> None:
    response = client.post(
        "/api/v1/feedback",
        headers={"X-API-Key": get_settings().api_key},
        json={"transaction_id": "tx-3", "label": "fraud"},
    )
    assert response.status_code == 202
    assert response.json()["label"] == "fraud"
