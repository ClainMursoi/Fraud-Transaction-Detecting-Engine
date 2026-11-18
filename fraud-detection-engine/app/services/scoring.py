"""Coordinate rules-first transaction scoring and operational decisions."""

from collections.abc import Mapping
from math import isfinite

from app.core.config import BankConfigLoader, get_settings
from app.ml.features import FeatureVector, extract_features, normalize_transaction
from app.ml.predictor import FraudPredictor
from app.rules.engine import apply_rules
from app.schemas.transactions import ScoreResponse, TransactionIn
from app.services.decision import Decision


class ScoringService:
    """Score transactions with bank rules first, then an optional predictor signal."""

    def __init__(
        self,
        *,
        predictor: FraudPredictor | None = None,
        config_loader: BankConfigLoader | None = None,
    ) -> None:
        self.settings = get_settings()
        self.predictor = predictor or FraudPredictor()
        self.config_loader = config_loader or BankConfigLoader(self.settings.bank_config_dir)

    def score(self, transaction: TransactionIn) -> ScoreResponse:
        """Score a transaction using the bank's rules and decision thresholds."""
        payload = normalize_transaction(transaction.model_dump(mode="python"))
        features = extract_features(payload)
        bank_id = transaction.bank_id
        bank_config = self.config_loader.load(bank_id)

        # Rules receive the normalized transaction so missing optional values are safe.
        rule_score, rule_reasons = apply_rules(payload, bank_config)
        model_score = self._validated_model_score(payload, features)

        # Noisy-OR combines independent evidence while keeping the result in [0, 1].
        risk_score = 1.0 - (1.0 - rule_score) * (1.0 - model_score)
        risk_score = min(max(risk_score, 0.0), 1.0)
        decision, reasons = self._decide(risk_score, rule_reasons, bank_config)
        return ScoreResponse(
            bank_id=bank_id,
            transaction_id=transaction.transaction_id,
            risk_score=round(risk_score, 6),
            decision=decision,
            reasons=reasons,
            model_version=self.predictor.version,
        )

    @staticmethod
    def _decide(
        risk_score: float,
        rule_reasons: list[str],
        bank_config: Mapping[str, object],
    ) -> tuple[Decision, list[str]]:
        """Apply configured score bands and any rule-level forced-decline policy."""
        thresholds = bank_config["thresholds"]
        if not isinstance(thresholds, Mapping):
            raise ValueError("Bank thresholds must be a mapping")
        approve_max = float(thresholds["approve_max"])
        review_max = float(thresholds["review_max"])
        decline_min = float(thresholds["decline_min"])

        configured_rules = bank_config["rules"]
        if not isinstance(configured_rules, Mapping):
            raise ValueError("Bank rules must be a mapping")
        forced_decline_reasons = {
            settings.get("reason", rule_id)
            for rule_id, settings in configured_rules.items()
            if isinstance(settings, Mapping)
            and settings.get("enabled", True) is True
            and settings.get("decision") == "decline"
        }

        reasons = list(dict.fromkeys(rule_reasons))
        if risk_score >= decline_min or any(reason in forced_decline_reasons for reason in reasons):
            if risk_score >= decline_min:
                reasons.append("decline_threshold_exceeded")
            return "decline", list(dict.fromkeys(reasons))
        if risk_score <= approve_max:
            return "approve", reasons

        # The review band extends up to (but excludes) the decline threshold.
        # review_max is retained in config as an escalation marker for reason text.
        reasons.append(
            "review_threshold_exceeded" if risk_score <= review_max else "elevated_review_risk"
        )
        return "review", list(dict.fromkeys(reasons))

    def _validated_model_score(
        self,
        payload: dict[str, object],
        features: FeatureVector,
    ) -> float:
        """Reject invalid predictor values rather than returning an invalid API score."""
        # The built-in predictor consumes the already computed vector. Keep the
        # original predictor interface as a fallback for injected implementations.
        predict_features = getattr(self.predictor, "predict_features", None)
        score = (
            predict_features(features)
            if callable(predict_features)
            else self.predictor.predict_proba(payload)
        )
        if not isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("Predictor must return a finite risk score between 0 and 1")
        return score
