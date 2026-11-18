"""Tests for configurable, channel-aware transaction rules."""

import pytest

from app.rules.engine import RuleConfigurationError, RuleEngine, apply_rules


def test_rules_apply_only_to_their_transaction_channel() -> None:
    engine = RuleEngine("configs/banks/default.yaml")

    card_matches = engine.evaluate({"channel": "card", "amount": 1200, "card_present": False})
    transfer_matches = engine.evaluate(
        {"channel": "transfer", "amount": 800, "is_new_payee": True}
    )
    mobile_matches = engine.evaluate(
        {"channel": "mobile", "amount": 100, "device_integrity_ok": False}
    )

    assert [match.reason for match in card_matches] == ["card_not_present_and_high_amount"]
    assert [match.reason for match in transfer_matches] == ["high_amount_to_new_beneficiary"]
    assert [match.reason for match in mobile_matches] == ["mobile_device_integrity_check_failed"]
    assert mobile_matches[0].decision == "decline"


def test_bank_configuration_controls_thresholds_and_decisions() -> None:
    engine = RuleEngine("configs/banks/example_bank.yaml")

    matches = engine.evaluate({"channel": "card", "amount": 3000})

    assert engine.bank_name == "example-bank"
    assert engine.review_threshold == 0.65
    assert engine.decline_threshold == 0.88
    assert [match.reason for match in matches] == ["bank_high_amount"]


def test_apply_rules_returns_capped_risk_and_triggered_reasons() -> None:
    engine = RuleEngine("configs/banks/default.yaml")
    transaction = {
        "channel": "card",
        "amount": 6000,
        "merchant_category": "gambling",
        "occurred_at": "2025-01-01T02:00:00Z",
    }

    risk_score, reasons = apply_rules(transaction, engine.config)

    assert risk_score == 0.52
    assert reasons == [
        "unusually_high_transaction_amount",
        "transaction_at_unusual_hour",
        "high_risk_merchant_category",
    ]


def test_transfer_and_mobile_rules_use_channel_specific_signals() -> None:
    engine = RuleEngine("configs/banks/default.yaml")

    transfer_matches = engine.evaluate(
        {
            "channel": "transfer",
            "amount": 6000,
            "is_new_beneficiary": True,
            "is_international": True,
            "is_first_international_transfer": True,
            "country": "US",
            "destination_country": "GB",
            "transfers_last_hour": 8,
        }
    )
    mobile_matches = engine.evaluate(
        {
            "channel": "mobile",
            "amount": 3500,
            "is_new_device": True,
            "is_new_location": True,
            "country": "US",
            "ip_country": "US",
            "occurred_at": "2025-01-01T02:00:00Z",
        }
    )

    assert {match.rule_id for match in transfer_matches} == {
        "unusually_high_amount",
        "high_velocity",
        "transfer_new_beneficiary_high_amount",
        "first_time_international_transfer",
    }
    assert {match.rule_id for match in mobile_matches} == {
        "unusually_high_amount",
        "unusual_hour",
        "mobile_new_device_high_amount",
        "mobile_high_risk_country",
        "mobile_unusual_hour_high_amount",
    }


def test_velocity_is_a_strong_signal_and_multiple_card_signals_compound() -> None:
    engine = RuleEngine("configs/banks/default.yaml")
    velocity_matches = engine.evaluate(
        {"channel": "transfer", "amount": 100, "transactions_last_hour": 12}
    )
    combined_matches = engine.evaluate(
        {
            "channel": "card",
            "amount": 900,
            "card_present": False,
            "billing_country": "US",
            "ip_country": "GB",
            "occurred_at": "2025-01-01T02:00:00Z",
        }
    )

    assert velocity_matches[0].risk_contribution == 0.32
    assert RuleEngine.score(velocity_matches) == 0.32
    assert RuleEngine.score(combined_matches) >= 0.68


def test_invalid_rule_threshold_is_rejected(tmp_path) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(
        "bank_name: invalid\nrules:\n  high_amount:\n    threshold: -1\n    risk_score: 0.2\n",
        encoding="utf-8",
    )

    with pytest.raises(RuleConfigurationError, match="non-negative number"):
        RuleEngine(config_path)