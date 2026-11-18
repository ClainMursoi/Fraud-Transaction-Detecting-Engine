"""Configurable, channel-aware transaction risk rules.

Each rule is deliberately small: it checks one fraud signal and returns a
bounded risk contribution plus a human-readable reason when it matches.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Literal

import yaml

Channel = Literal["card", "transfer", "mobile"]
RuleDecision = Literal["review", "decline"]
SUPPORTED_CHANNELS = frozenset({"card", "transfer", "mobile"})
Transaction = Mapping[str, object]
RuleSettings = Mapping[str, object]
RuleFunction = Callable[[Transaction, RuleSettings], bool]


class RuleConfigurationError(ValueError):
    """Raised when a configured rule cannot be safely evaluated."""


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """A triggered rule with its individual risk contribution and explanation."""

    rule_id: str
    risk_contribution: float
    reason: str
    decision: RuleDecision

    @property
    def risk_score(self) -> float:
        """Backward-compatible alias for the individual contribution."""
        return self.risk_contribution


@dataclass(frozen=True, slots=True)
class _Rule:
    rule_id: str
    settings: dict[str, object]
    check: RuleFunction
    risk_contribution: float
    reason: str
    decision: RuleDecision


def _number(value: object) -> float | None:
    """Convert finite numeric values, explicitly excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    return converted if isfinite(converted) else None


def _amount(transaction: Transaction) -> float | None:
    return _number(transaction.get("amount"))


def _country(value: object) -> str | None:
    return value.strip().upper() if isinstance(value, str) and value.strip() else None


def _transaction_hour(transaction: Transaction) -> int | None:
    """Get the hour component from a datetime or ISO-8601 timestamp."""
    occurred_at = transaction.get("occurred_at")
    if isinstance(occurred_at, datetime):
        return occurred_at.hour
    if isinstance(occurred_at, str):
        try:
            return datetime.fromisoformat(occurred_at.replace("Z", "+00:00")).hour
        except ValueError:
            return None
    return None


def _threshold_for_channel(settings: RuleSettings, channel: str) -> float | None:
    """Read a shared amount threshold or an optional per-channel threshold."""
    by_channel = settings.get("thresholds")
    if isinstance(by_channel, Mapping):
        return _number(by_channel.get(channel))
    return _number(settings.get("threshold"))


def _high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    channel = transaction.get("channel", "card")
    amount = _amount(transaction)
    threshold = _threshold_for_channel(settings, str(channel))
    return amount is not None and threshold is not None and amount >= threshold


def _unusual_hour(transaction: Transaction, settings: RuleSettings) -> bool:
    hour = _transaction_hour(transaction)
    start = _number(settings.get("start_hour", 1))
    end = _number(settings.get("end_hour", 5))
    if hour is None or start is None or end is None or not 0 <= start < 24 or not 0 <= end < 24:
        return False
    # The window is [start, end); a reversed range covers midnight.
    return start <= hour < end if start <= end else hour >= start or hour < end


def _high_velocity(transaction: Transaction, settings: RuleSettings) -> bool:
    """Use a supplied short-window count; no storage/history is assumed."""
    channel = transaction.get("channel", "card")
    channel_key = f"{channel}_transactions_last_hour"
    count = transaction.get(
        channel_key,
        transaction.get(
            "transactions_last_10_minutes",
            transaction.get(
                "transactions_last_hour",
                transaction.get("transfers_last_hour", transaction.get("transfer_count_1h")),
            ),
        ),
    )
    actual = _number(count)
    threshold = _number(settings.get("count_threshold", settings.get("threshold", 5)))
    return actual is not None and threshold is not None and actual >= threshold


def _all_channels(transaction: Transaction, settings: RuleSettings) -> bool:
    enabled_channels = settings.get("channels", list(SUPPORTED_CHANNELS))
    channel = transaction.get("channel", "card")
    return (
        isinstance(enabled_channels, (list, tuple, set, frozenset))
        and channel in enabled_channels
    )


def _unusually_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    """Shared amount signal, with an optional threshold override per channel."""
    return _all_channels(transaction, settings) and _high_amount(transaction, settings)


def _unusual_hour_all(transaction: Transaction, settings: RuleSettings) -> bool:
    return _all_channels(transaction, settings) and _unusual_hour(transaction, settings)


def _high_velocity_all(transaction: Transaction, settings: RuleSettings) -> bool:
    return _all_channels(transaction, settings) and _high_velocity(transaction, settings)


def _high_risk_merchant(transaction: Transaction, settings: RuleSettings) -> bool:
    categories = settings.get("categories", ())
    category = transaction.get("merchant_category")
    if transaction.get("channel") != "card" or not isinstance(category, str):
        return False
    configured = {item.casefold() for item in categories if isinstance(item, str)} if isinstance(categories, (list, tuple, set)) else set()
    return category.strip().casefold() in configured


def _card_not_present_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    return (
        transaction.get("channel") == "card"
        and transaction.get("card_present") is False
        and _high_amount(transaction, settings)
    )


def _card_location_inconsistency(transaction: Transaction, _settings: RuleSettings) -> bool:
    del _settings
    if transaction.get("channel") != "card":
        return False
    pairs = (
        (transaction.get("billing_country"), transaction.get("ip_country")),
        (transaction.get("card_country"), transaction.get("ip_country")),
        (transaction.get("country"), transaction.get("ip_country")),
    )
    return any(
        _country(first) is not None
        and _country(second) is not None
        and _country(first) != _country(second)
        for first, second in pairs
    )


def _transfer_new_beneficiary_high_amount(
    transaction: Transaction, settings: RuleSettings
) -> bool:
    new_beneficiary = transaction.get("is_new_beneficiary") is True or transaction.get("is_new_payee") is True
    return transaction.get("channel") == "transfer" and new_beneficiary and _high_amount(transaction, settings)


def _first_time_international_transfer(transaction: Transaction, _settings: RuleSettings) -> bool:
    del _settings
    if transaction.get("channel") != "transfer":
        return False
    first_time = (
        transaction.get("is_first_international_transfer") is True
        or transaction.get("is_first_international_beneficiary") is True
    )
    international = transaction.get("is_international") is True
    origin = _country(transaction.get("origin_country", transaction.get("country")))
    destination = _country(transaction.get("destination_country"))
    international = international or (origin is not None and destination is not None and origin != destination)
    return international and first_time


def _high_amount_to_new_account(transaction: Transaction, settings: RuleSettings) -> bool:
    if transaction.get("channel") != "transfer" or not _high_amount(transaction, settings):
        return False
    is_new = transaction.get("is_new_beneficiary_account") is True
    age = _number(transaction.get("beneficiary_account_age_days"))
    max_age = _number(settings.get("max_account_age_days", 30))
    return is_new or (age is not None and max_age is not None and age <= max_age)


def _legacy_international_transfer(transaction: Transaction, _settings: RuleSettings) -> bool:
    """Retain the older international-transfer signal for existing YAML configs."""
    del _settings
    if transaction.get("channel") != "transfer":
        return False
    origin = _country(transaction.get("origin_country", transaction.get("country")))
    destination = _country(transaction.get("destination_country"))
    return (
        transaction.get("is_international") is True
        or (origin is not None and destination is not None and origin != destination)
    )


def _repeated_failed_attempts(transaction: Transaction, settings: RuleSettings) -> bool:
    attempts = _number(transaction.get("recent_failed_attempts"))
    threshold = _number(settings.get("threshold", 3))
    return attempts is not None and threshold is not None and attempts >= threshold


def _new_device_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    return transaction.get("is_new_device") is True and _high_amount(transaction, settings)


def _legacy_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    return _high_amount(transaction, settings)


def _legacy_mobile_integrity_failure(transaction: Transaction, _settings: RuleSettings) -> bool:
    del _settings
    return transaction.get("channel") == "mobile" and transaction.get("device_integrity_ok") is False


def _legacy_young_account_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    age = _number(transaction.get("account_age_days"))
    max_age = _number(settings.get("max_account_age_days", 30))
    return (
        transaction.get("channel") in SUPPORTED_CHANNELS
        and age is not None
        and max_age is not None
        and age <= max_age
        and _high_amount(transaction, settings)
    )


def _legacy_new_payee_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    return _transfer_new_beneficiary_high_amount(transaction, settings)


def _legacy_mobile_new_device(transaction: Transaction, _settings: RuleSettings) -> bool:
    del _settings
    return transaction.get("channel") == "mobile" and transaction.get("is_new_device") is True


def _legacy_mobile_location(transaction: Transaction, settings: RuleSettings) -> bool:
    return _mobile_high_risk_country(transaction, settings)


def _legacy_high_transfer_velocity(transaction: Transaction, settings: RuleSettings) -> bool:
    return transaction.get("channel") == "transfer" and _high_velocity(transaction, settings)


def _legacy_card_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    return transaction.get("channel") == "card" and _high_amount(transaction, settings)


def _legacy_transfer_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    return transaction.get("channel") == "transfer" and _high_amount(transaction, settings)


def _legacy_mobile_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    return transaction.get("channel") == "mobile" and _high_amount(transaction, settings)


def _legacy_card_unusual_hour(transaction: Transaction, settings: RuleSettings) -> bool:
    return transaction.get("channel") == "card" and _unusual_hour(transaction, settings)


def _legacy_mobile_unusual_hour(transaction: Transaction, settings: RuleSettings) -> bool:
    return transaction.get("channel") == "mobile" and _unusual_hour(transaction, settings)


def _legacy_card_not_present_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    return _card_not_present_high_amount(transaction, settings)


def _legacy_new_payee(transaction: Transaction, _settings: RuleSettings) -> bool:
    del _settings
    return transaction.get("channel") == "transfer" and (
        transaction.get("is_new_beneficiary") is True or transaction.get("is_new_payee") is True
    )


def _mobile_new_device_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    return (
        transaction.get("channel") == "mobile"
        and transaction.get("is_new_device") is True
        and _high_amount(transaction, settings)
    )


def _mobile_high_risk_country(transaction: Transaction, settings: RuleSettings) -> bool:
    if transaction.get("channel") != "mobile":
        return False
    country = _country(transaction.get("ip_country", transaction.get("country")))
    raw_countries = settings.get("countries", settings.get("high_risk_countries", ()))
    high_risk_countries = {
        item.upper() for item in raw_countries if isinstance(item, str)
    } if isinstance(raw_countries, (list, tuple, set)) else set()
    # Explicit enrichment flags and new locations support banks without a static list.
    return (
        transaction.get("is_high_risk_country") is True
        or transaction.get("is_new_location") is True
        or (country is not None and country in high_risk_countries)
    )


def _mobile_unusual_hour_high_amount(transaction: Transaction, settings: RuleSettings) -> bool:
    return (
        transaction.get("channel") == "mobile"
        and _unusual_hour(transaction, settings)
        and _high_amount(transaction, settings)
    )


# Stable identifiers let bank YAML policies tune contribution, reason, and enablement.
_RULES: dict[str, RuleFunction] = {
    "unusually_high_amount": _unusually_high_amount,
    "unusual_hour": _unusual_hour_all,
    "high_velocity": _high_velocity_all,
    "card_high_risk_merchant_category": _high_risk_merchant,
    "card_not_present_high_amount": _card_not_present_high_amount,
    "card_location_inconsistency": _card_location_inconsistency,
    "transfer_new_beneficiary_high_amount": _transfer_new_beneficiary_high_amount,
    "first_time_international_transfer": _first_time_international_transfer,
    "high_amount_to_new_account": _high_amount_to_new_account,
    "mobile_new_device_high_amount": _mobile_new_device_high_amount,
    "mobile_high_risk_country": _mobile_high_risk_country,
    "mobile_unusual_hour_high_amount": _mobile_unusual_hour_high_amount,
    # Keep legacy keys usable for existing bank YAML files.
    "card_high_amount": _legacy_card_high_amount,
    "transfer_high_amount": _legacy_transfer_high_amount,
    "mobile_high_amount": _legacy_mobile_high_amount,
    "card_unusual_hour": _legacy_card_unusual_hour,
    "mobile_unusual_hour": _legacy_mobile_unusual_hour,
    "high_transfer_velocity": _legacy_high_transfer_velocity,
    "transfer_new_beneficiary": _legacy_new_payee,
    "international_transfer": _legacy_international_transfer,
    "unusual_location": _legacy_mobile_location,
    "mobile_new_device": _legacy_mobile_new_device,
    "high_amount": _legacy_high_amount,
    "repeated_failed_attempts": _repeated_failed_attempts,
    "new_device_high_amount": _new_device_high_amount,
    "new_payee_high_amount": _legacy_new_payee_high_amount,
    "mobile_integrity_failure": _legacy_mobile_integrity_failure,
    "young_account_high_amount": _legacy_young_account_high_amount,
    "card_not_present_high_amount": _legacy_card_not_present_high_amount,
}


def _load_rules(raw_rules: object) -> list[_Rule]:
    if not isinstance(raw_rules, Mapping):
        raise RuleConfigurationError("The 'rules' config must be a mapping")
    configured: list[_Rule] = []
    for rule_id, raw_settings in raw_rules.items():
        if not isinstance(rule_id, str) or rule_id not in _RULES:
            raise RuleConfigurationError(f"Unknown rule ID: {rule_id!r}")
        if not isinstance(raw_settings, Mapping):
            raise RuleConfigurationError(f"Settings for rule '{rule_id}' must be a mapping")
        settings = dict(raw_settings)
        enabled = settings.get("enabled", True)
        if not isinstance(enabled, bool):
            raise RuleConfigurationError(f"Rule '{rule_id}' enabled must be boolean")
        if not enabled:
            continue

        for key in ("threshold", "max_account_age_days", "count_threshold"):
            if key in settings:
                value = _number(settings[key])
                if value is None or value < 0:
                    raise RuleConfigurationError(f"Rule '{rule_id}' {key} must be a non-negative number")
        per_channel_thresholds = settings.get("thresholds")
        if per_channel_thresholds is not None:
            if not isinstance(per_channel_thresholds, Mapping) or any(
                channel not in SUPPORTED_CHANNELS
                or _number(value) is None
                or _number(value) < 0
                for channel, value in per_channel_thresholds.items()
            ):
                raise RuleConfigurationError(
                    f"Rule '{rule_id}' thresholds must map supported channels to non-negative numbers"
                )
        for key in ("categories", "countries", "high_risk_countries", "channels"):
            value = settings.get(key)
            if value is not None and (
                not isinstance(value, (list, tuple, set, frozenset))
                or not all(isinstance(item, str) for item in value)
            ):
                raise RuleConfigurationError(f"Rule '{rule_id}' {key} must be a list of strings")
        for key in ("start_hour", "end_hour"):
            if key in settings:
                value = _number(settings[key])
                if value is None or not value.is_integer() or not 0 <= value < 24:
                    raise RuleConfigurationError(f"Rule '{rule_id}' {key} must be an integer from 0 to 23")

        raw_contribution = settings.get("risk_contribution", settings.get("risk_score", 0.1))
        contribution = _number(raw_contribution)
        if contribution is None or not 0 <= contribution <= 1:
            raise RuleConfigurationError(f"Rule '{rule_id}' risk_contribution must be between 0 and 1")
        reason = settings.get("reason", rule_id.replace("_", " "))
        if not isinstance(reason, str) or not reason.strip():
            raise RuleConfigurationError(f"Rule '{rule_id}' reason must be non-empty text")
        decision = settings.get("decision", "review")
        if not isinstance(decision, str) or decision not in {"review", "decline"}:
            raise RuleConfigurationError(f"Rule '{rule_id}' decision must be 'review' or 'decline'")

        configured.append(
            _Rule(
                rule_id=rule_id,
                settings=settings,
                check=_RULES[rule_id],
                risk_contribution=contribution,
                reason=reason,
                decision=decision,
            )
        )
    return configured


def _evaluate(transaction: Transaction, rules: list[_Rule]) -> list[RuleMatch]:
    """Evaluate rules, treating absent optional indicators as no match."""
    channel = transaction.get("channel", "card")
    if not isinstance(channel, str) or channel not in SUPPORTED_CHANNELS:
        raise ValueError(f"Unsupported transaction channel: {channel!r}")
    matches: list[RuleMatch] = []
    for rule in rules:
        try:
            matched = rule.check(transaction, rule.settings)
        except (TypeError, ValueError, OverflowError):
            # Missing or malformed optional data must not crash transaction scoring.
            matched = False
        if matched:
            matches.append(
                RuleMatch(
                    rule_id=rule.rule_id,
                    risk_contribution=rule.risk_contribution,
                    reason=rule.reason,
                    decision=rule.decision,
                )
            )
    return matches


def apply_rules(transaction: dict[str, object], config: dict[str, object]) -> tuple[float, list[str]]:
    """Return the capped sum of rule contributions and their readable reasons."""
    matches = _evaluate(transaction, _load_rules(config.get("rules")))
    total_risk = min(sum(match.risk_contribution for match in matches), 1.0)
    reasons = list(dict.fromkeys(match.reason for match in matches))
    return total_risk, reasons


class RuleEngine:
    """Evaluate an existing bank YAML ruleset or a provided configuration mapping."""

    def __init__(self, config_path: str | Path | Mapping[str, object]) -> None:
        if isinstance(config_path, Mapping):
            self.config = dict(config_path)
        else:
            path = Path(config_path).expanduser()
            if not path.is_absolute() and not path.is_file():
                path = Path(__file__).resolve().parents[2] / path
            if not path.is_file():
                raise FileNotFoundError(f"Bank configuration file not found: {path}")
            with path.open(encoding="utf-8") as config_file:
                loaded = yaml.safe_load(config_file)
            if not isinstance(loaded, Mapping):
                raise RuleConfigurationError(f"Bank configuration must be a YAML mapping: {path}")
            self.config = dict(loaded)
        self.bank_name = str(self.config.get("bank_name", "unnamed-bank"))
        self._rules = _load_rules(self.config.get("rules"))
        decision_config = self.config.get("decision", {})
        if not isinstance(decision_config, Mapping):
            raise RuleConfigurationError("The 'decision' config must be a mapping")
        review_threshold = _number(decision_config.get("review_threshold", 0.7))
        decline_threshold = _number(decision_config.get("decline_threshold", 0.9))
        if (
            review_threshold is None
            or decline_threshold is None
            or not 0 <= review_threshold <= decline_threshold <= 1
        ):
            raise RuleConfigurationError("Decision thresholds must satisfy 0 <= review <= decline <= 1")
        self.review_threshold = review_threshold
        self.decline_threshold = decline_threshold

    def evaluate(self, transaction: Transaction) -> list[RuleMatch]:
        """Return detailed matches with individual contribution amounts."""
        return _evaluate(transaction, self._rules)

    @staticmethod
    def score(matches: list[RuleMatch]) -> float:
        """Add rule signals and cap the result to the valid risk range."""
        return min(sum(match.risk_contribution for match in matches), 1.0)

    @property
    def decline_reasons(self) -> set[str]:
        """Return reasons for enabled rules configured to force a decline."""
        return {rule.reason for rule in self._rules if rule.decision == "decline"}
