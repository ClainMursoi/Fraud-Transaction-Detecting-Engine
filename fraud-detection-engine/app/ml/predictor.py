"""Baseline risk predictor; replace with a validated model artifact in production."""

from collections.abc import Mapping
from math import exp

from app.ml.features import extract_features


class FraudPredictor:
    """Transparent weighted baseline returning a risk score in [0, 1]."""

    version = "baseline-1"

    def predict_proba(self, transaction: dict[str, object]) -> float:
        """Predict from raw transaction data using the shared feature pipeline."""
        return self.predict_features(extract_features(transaction))

    def predict_features(self, features: Mapping[str, float]) -> float:
        """Predict from an already extracted feature vector."""
        logit = (
            -3.0
            + 1.5 * features.get("amount_log", 0.0)
            + 1.8 * features.get("new_device", 0.0)
            + 1.2 * features.get("young_account", 0.0)
            + 2.0 * features.get("failed_attempts", 0.0)
        )
        return 1.0 / (1.0 + exp(-logit))
