"""Tests for normalized transaction feature extraction."""

from app.ml.features import extract_features, normalize_transaction


def test_missing_features_use_safe_defaults_without_mutating_input() -> None:
    transaction: dict[str, object] = {"transaction_id": "sparse-tx"}

    normalized = normalize_transaction(transaction)
    features = extract_features(transaction)

    assert transaction == {"transaction_id": "sparse-tx"}
    assert normalized["channel"] == "card"
    assert normalized["amount"] == 0.0
    assert features["amount_log"] == 0.0
    assert features["failed_attempts"] == 0.0
    assert features["channel_card"] == 1.0
    assert features["channel_transfer"] == 0.0


def test_transfer_and_mobile_features_are_channel_specific() -> None:
    transfer_features = extract_features(
        {
            "channel": "TRANSFER",
            "amount": "1500.00",
            "is_new_beneficiary": True,
            "destination_country": "GB",
            "country": "US",
            "transfers_last_hour": 15,
        }
    )
    mobile_features = extract_features(
        {
            "channel": "mobile",
            "is_new_device": True,
            "device_integrity_ok": False,
            "country": "US",
            "ip_country": "GB",
            "occurred_at": "2025-01-01T03:00:00Z",
        }
    )

    assert transfer_features["channel_transfer"] == 1.0
    assert transfer_features["new_beneficiary"] == 1.0
    assert transfer_features["international_transfer"] == 1.0
    assert transfer_features["transfer_velocity"] == 1.0
    assert transfer_features["card_unusual_hour"] == 0.0
    assert mobile_features["channel_mobile"] == 1.0
    assert mobile_features["new_device"] == 1.0
    assert mobile_features["unusual_location"] == 1.0
    assert mobile_features["device_integrity_failure"] == 1.0
    assert mobile_features["mobile_unusual_hour"] == 1.0