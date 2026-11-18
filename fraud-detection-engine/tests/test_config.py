"""Tests for loading and applying local bank scoring configuration."""

import pytest

from app.core.config import BankConfigLoader
from app.schemas.transactions import TransactionIn
from app.services.scoring import ScoringService


class _LowRiskPredictor:
    """Deterministic predictor for configuration integration tests."""

    version = "test"

    def predict_proba(self, transaction: dict[str, object]) -> float:
        return 0.05


class _StaticPredictor:
    """Predictor returning a fixed score for threshold comparisons."""

    version = "test"

    def __init__(self, risk_score: float) -> None:
        self.risk_score = risk_score

    def predict_proba(self, transaction: dict[str, object]) -> float:
        return self.risk_score


def test_loader_selects_bank_config_and_returns_independent_copy() -> None:
    loader = BankConfigLoader()
    default_config = loader.load()
    demo_config = loader.load("demo_bank")

    assert default_config["bank_name"] == "default"
    assert demo_config["bank_name"] == "demo-bank"
    assert demo_config["thresholds"] != default_config["thresholds"]

    demo_config["bank_name"] = "mutated"
    assert loader.load("demo_bank")["bank_name"] == "demo-bank"


def test_loader_rejects_unknown_bank_instead_of_falling_back() -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        BankConfigLoader().load("not_a_configured_bank")


def test_scoring_uses_selected_bank_rule_configuration() -> None:
    service = ScoringService(
        predictor=_LowRiskPredictor(),  # type: ignore[arg-type]
        config_loader=BankConfigLoader(),
    )

    result = service.score(
        TransactionIn(
            transaction_id="demo-tx",
            bank_id="demo_bank",
            channel="mobile",
            amount=100,
            device_integrity_ok=False,
        )
    )

    assert result.bank_id == "demo_bank"
    assert result.decision == "decline"
    assert "mobile_device_integrity_check_failed" in result.reasons


def test_scoring_uses_bank_specific_decision_thresholds() -> None:
    transaction = TransactionIn(
        transaction_id="threshold-tx",
        channel="card",
        amount=100,
    )
    default_service = ScoringService(
        predictor=_StaticPredictor(0.79),  # type: ignore[arg-type]
        config_loader=BankConfigLoader(),
    )
    demo_service = ScoringService(
        predictor=_StaticPredictor(0.79),  # type: ignore[arg-type]
        config_loader=BankConfigLoader(),
    )

    default_result = default_service.score(transaction)
    demo_result = demo_service.score(transaction.model_copy(update={"bank_id": "demo_bank"}))

    assert default_result.decision == "review"
    assert demo_result.decision == "decline"


def test_scoring_does_not_escalate_every_rule_match_to_review() -> None:
    service = ScoringService(
        predictor=_LowRiskPredictor(),  # type: ignore[arg-type]
        config_loader=BankConfigLoader(),
    )

    result = service.score(
        TransactionIn(
            transaction_id="small-signal",
            channel="mobile",
            amount=850,
            is_new_device=True,
        )
    )

    assert result.decision == "review"
    assert result.reasons == [
        "high_amount_from_new_mobile_device",
        "review_threshold_exceeded",
    ]


def test_default_policy_examples_cover_approve_review_and_decline() -> None:
    service = ScoringService(config_loader=BankConfigLoader())
    examples = [
        TransactionIn(
            transaction_id="normal-card",
            channel="card",
            amount=45,
            merchant_category="grocery",
            card_present=True,
            country="US",
            ip_country="US",
            occurred_at="2025-01-01T14:00:00Z",
        ),
        TransactionIn(
            transaction_id="review-transfer",
            channel="transfer",
            amount=1200,
            is_new_beneficiary=True,
            is_international=True,
            is_first_international_transfer=True,
            transactions_last_hour=8,
        ),
        TransactionIn(
            transaction_id="decline-mobile",
            channel="mobile",
            amount=8000,
            is_new_device=True,
            is_high_risk_country=True,
            ip_country="RU",
            country="US",
            device_integrity_ok=False,
            occurred_at="2025-01-01T02:00:00Z",
        ),
    ]

    responses = [service.score(example) for example in examples]

    assert [response.decision for response in responses] == ["approve", "review", "decline"]