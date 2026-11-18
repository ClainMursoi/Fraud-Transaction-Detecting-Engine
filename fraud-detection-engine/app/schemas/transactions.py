"""Schemas for transaction scoring."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TransactionIn(BaseModel):
    """Transaction attributes accepted by the scoring API."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1, max_length=128)
    bank_id: str = Field(default="default", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    channel: Literal["card", "transfer", "mobile"] = "card"
    amount: float = Field(gt=0, le=10_000_000)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    merchant_category: str = Field(default="unknown", max_length=64)
    country: str = Field(default="US", min_length=2, max_length=2)
    billing_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    card_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    destination_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    ip_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    is_new_device: bool = False
    is_new_payee: bool = False
    is_new_beneficiary: bool | None = None
    is_international: bool | None = None
    is_first_international_transfer: bool = False
    is_first_international_beneficiary: bool = False
    is_new_beneficiary_account: bool = False
    is_high_risk_country: bool = False
    beneficiary_account_age_days: int | None = Field(default=None, ge=0)
    is_new_location: bool = False
    transactions_last_hour: int | None = Field(default=None, ge=0, le=10_000)
    transactions_last_10_minutes: int | None = Field(default=None, ge=0, le=10_000)
    transfers_last_hour: int | None = Field(default=None, ge=0, le=10_000)
    card_present: bool | None = None
    device_integrity_ok: bool | None = None
    account_age_days: int = Field(default=365, ge=0)
    recent_failed_attempts: int = Field(default=0, ge=0, le=100)
    occurred_at: datetime | None = None


class ScoreResponse(BaseModel):
    bank_id: str
    transaction_id: str
    risk_score: float = Field(ge=0, le=1)
    decision: Literal["approve", "review", "decline"]
    reasons: list[str]
    model_version: str


# Backwards-compatible name used by the existing route and clients.
ScoreOut = ScoreResponse
