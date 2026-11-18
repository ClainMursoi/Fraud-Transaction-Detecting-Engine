"""Normalize transaction inputs and extract deterministic model features."""

from collections.abc import Mapping
from datetime import datetime
from math import isfinite, log1p
from typing import Final

TransactionData = Mapping[str, object]
NormalizedTransaction = dict[str, object]
FeatureVector = dict[str, float]

_MAX_AMOUNT: Final[float] = 10_000_000.0
_HIGH_RISK_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"gambling", "cryptocurrency", "money_transfer"}
)


def _number(value: object, default: float = 0.0) -> float:
    """Return a finite numeric value, using a safe default for missing/bad data."""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)  # Also handles numeric strings from non-API callers.
    except (OverflowError, TypeError, ValueError):
        return default
    return number if isfinite(number) else default


def _boolean(value: object, default: bool = False) -> bool:
    """Accept real booleans only; avoid surprising truthiness for strings/numbers."""
    return value if isinstance(value, bool) else default


def _country(value: object) -> str | None:
    """Normalize a two-letter country code or return None for absent/invalid data."""
    if not isinstance(value, str):
        return None
    country = value.strip().upper()
    return country if len(country) == 2 and country.isalpha() else None


def normalize_transaction(transaction: TransactionData) -> NormalizedTransaction:
    """Return a defensive, normalized copy with safe defaults for optional fields.

    Missing amounts become zero for feature/rule evaluation. Public API validation
    still requires a positive amount; this behavior protects internal callers and
    incomplete historical records from raising ``KeyError`` or conversion errors.
    """
    normalized: NormalizedTransaction = dict(transaction)

    raw_channel = transaction.get("channel", "card")
    channel = raw_channel.strip().lower() if isinstance(raw_channel, str) else "card"
    normalized["channel"] = channel or "card"

    normalized["amount"] = max(_number(transaction.get("amount")), 0.0)
    normalized["account_age_days"] = max(_number(transaction.get("account_age_days"), 365.0), 0.0)
    normalized["recent_failed_attempts"] = max(
        _number(transaction.get("recent_failed_attempts")), 0.0
    )

    for field in ("is_new_device", "is_new_payee", "is_new_location"):
        normalized[field] = _boolean(transaction.get(field))

    new_beneficiary = transaction.get("is_new_beneficiary")
    normalized["is_new_beneficiary"] = _boolean(
        new_beneficiary,
        _boolean(transaction.get("is_new_payee")),
    )
    normalized["is_new_payee"] = _boolean(
        transaction.get("is_new_payee"),
        _boolean(new_beneficiary),
    )

    explicit_international = transaction.get("is_international")
    origin_country = _country(transaction.get("origin_country", transaction.get("country")))
    destination_country = _country(transaction.get("destination_country"))
    derived_international = (
        origin_country != destination_country
        if origin_country is not None and destination_country is not None
        else False
    )
    normalized["is_international"] = _boolean(explicit_international, derived_international)

    normalized["country"] = _country(transaction.get("country")) or "US"
    normalized["destination_country"] = destination_country
    normalized["ip_country"] = _country(transaction.get("ip_country"))
    normalized["card_present"] = (
        transaction.get("card_present")
        if isinstance(transaction.get("card_present"), bool)
        else None
    )
    normalized["device_integrity_ok"] = (
        transaction.get("device_integrity_ok")
        if isinstance(transaction.get("device_integrity_ok"), bool)
        else None
    )

    transfer_count = transaction.get("transfers_last_hour", transaction.get("recent_transfer_count"))
    normalized["transfers_last_hour"] = (
        max(_number(transfer_count), 0.0) if transfer_count is not None else None
    )

    merchant_category = transaction.get("merchant_category", "unknown")
    normalized["merchant_category"] = (
        merchant_category.strip().casefold() if isinstance(merchant_category, str) else "unknown"
    )
    return normalized


def _transaction_hour(transaction: TransactionData) -> int | None:
    """Read an hour from a datetime or a valid ISO-8601 timestamp string."""
    occurred_at = transaction.get("occurred_at")
    if isinstance(occurred_at, datetime):
        return occurred_at.hour
    if isinstance(occurred_at, str):
        try:
            return datetime.fromisoformat(occurred_at.replace("Z", "+00:00")).hour
        except ValueError:
            return None
    return None


def extract_features(transaction: TransactionData) -> FeatureVector:
    """Normalize a transaction and emit bounded numeric features for all channels.

    Channel-specific fields are zero when they do not apply or their source data
    is missing. Feature extraction is deliberately deterministic and uses no
    external services or transaction history lookups.
    """
    normalized = normalize_transaction(transaction)
    channel = str(normalized["channel"])
    amount = min(_number(normalized.get("amount")), _MAX_AMOUNT)
    account_age_days = _number(normalized.get("account_age_days"), 365.0)
    failed_attempts = _number(normalized.get("recent_failed_attempts"))
    transfer_count = _number(normalized.get("transfers_last_hour"))
    merchant_category = str(normalized.get("merchant_category", "unknown"))
    hour = _transaction_hour(normalized)

    unusual_hour = hour is not None and 1 <= hour < 5
    ip_country = normalized.get("ip_country")
    account_country = normalized.get("country")
    unusual_location = _boolean(normalized.get("is_new_location")) or (
        isinstance(ip_country, str)
        and isinstance(account_country, str)
        and ip_country != account_country
    )

    return {
        # Shared model features retained for the baseline predictor.
        "amount_log": min(log1p(amount) / log1p(_MAX_AMOUNT), 1.0),
        "new_device": float(_boolean(normalized.get("is_new_device"))),
        "young_account": float(account_age_days < 30),
        "failed_attempts": min(failed_attempts / 10.0, 1.0),
        "channel_card": float(channel == "card"),
        "channel_transfer": float(channel == "transfer"),
        "channel_mobile": float(channel == "mobile"),
        # Card features.
        "card_not_present": float(
            channel == "card" and normalized.get("card_present") is False
        ),
        "high_risk_merchant_category": float(
            channel == "card" and merchant_category in _HIGH_RISK_CATEGORIES
        ),
        "card_unusual_hour": float(channel == "card" and unusual_hour),
        # Transfer features.
        "new_beneficiary": float(
            channel == "transfer" and _boolean(normalized.get("is_new_beneficiary"))
        ),
        "international_transfer": float(
            channel == "transfer" and _boolean(normalized.get("is_international"))
        ),
        "transfer_velocity": min(transfer_count / 10.0, 1.0) if channel == "transfer" else 0.0,
        # Mobile features.
        "mobile_unusual_hour": float(channel == "mobile" and unusual_hour),
        "unusual_location": float(channel == "mobile" and unusual_location),
        "high_risk_country": float(
            channel == "mobile" and _boolean(normalized.get("is_high_risk_country"))
        ),
        "device_integrity_failure": float(
            channel == "mobile" and normalized.get("device_integrity_ok") is False
        ),
    }
