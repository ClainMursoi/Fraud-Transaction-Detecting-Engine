"""Continuous synthetic transaction producer for the local scoring demo."""

from __future__ import annotations

import asyncio
import random
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from app.schemas.transactions import TransactionIn
from app.services.scoring import ScoringService

COUNTRIES = ("US", "CA", "GB", "DE", "FR", "AU", "SG", "BR", "MX", "NG")


def generate_transaction(index: int, fraud_rate: float = 0.15) -> tuple[TransactionIn, bool]:
    """Generate one valid transaction and whether it is a suspicious scenario."""
    suspicious = random.random() < fraud_rate
    channel = random.choice(("card", "transfer", "mobile"))
    country = random.choices(COUNTRIES, weights=(55, 8, 8, 6, 5, 4, 4, 4, 3, 3))[0]
    amount = round(
        random.uniform(900, 12_000) if suspicious else random.lognormvariate(3.5, 0.9), 2
    )
    amount = min(max(amount, 1.0), 10_000_000.0)
    velocity = random.randint(6, 12) if suspicious else random.choices((0, 1, 2, 3), (55, 25, 15, 5))[0]
    now = datetime.now(timezone.utc)
    if suspicious and random.random() < 0.35:
        occurred_at = now.replace(hour=random.choice((1, 2, 3, 4)), minute=random.randrange(60), second=0, microsecond=0)
        if occurred_at > now:
            occurred_at -= timedelta(days=1)
    else:
        occurred_at = now - timedelta(minutes=random.randrange(24 * 60))

    payload: dict[str, Any] = {
        "transaction_id": f"live-{index:08d}-{uuid.uuid4().hex[:8]}",
        "bank_id": "default",
        "channel": channel,
        "amount": amount,
        "currency": random.choice(("USD", "USD", "USD", "EUR", "GBP", "CAD")),
        "country": country,
        "is_new_device": suspicious and random.random() < 0.75 or random.random() < 0.04,
        "is_new_location": suspicious and random.random() < 0.55,
        "transactions_last_hour": velocity,
        "transactions_last_10_minutes": min(velocity, random.randint(0, 7)),
        "account_age_days": random.randint(1, 25) if suspicious and random.random() < 0.45 else random.randint(90, 2500),
        "recent_failed_attempts": random.randint(4, 8) if suspicious and random.random() < 0.3 else random.choices((0, 1, 2), (80, 15, 5))[0],
        "occurred_at": occurred_at,
    }

    if channel == "card":
        different_country = random.choice(tuple(code for code in COUNTRIES if code != country))
        payload.update(
            {
                "merchant_category": random.choice(("gambling", "cryptocurrency", "money_transfer"))
                if suspicious and random.random() < 0.55
                else random.choice(("groceries", "restaurants", "fuel", "travel", "retail", "utilities")),
                "billing_country": country,
                "card_country": country,
                "ip_country": different_country if suspicious and random.random() < 0.55 else country,
                "card_present": False if suspicious and random.random() < 0.7 else random.choice((True, False)),
            }
        )
    elif channel == "transfer":
        is_international = suspicious and random.random() < 0.6
        destination = random.choice(tuple(code for code in COUNTRIES if code != country)) if is_international else country
        payload.update(
            {
                "destination_country": destination,
                "is_international": is_international,
                "is_new_beneficiary": suspicious and random.random() < 0.8,
                "is_new_payee": suspicious and random.random() < 0.8,
                "is_first_international_transfer": is_international,
                "is_new_beneficiary_account": suspicious and random.random() < 0.5,
                "beneficiary_account_age_days": random.randint(0, 14) if suspicious else random.randint(30, 2000),
                "transfers_last_hour": velocity,
            }
        )
    else:
        payload.update(
            {
                "ip_country": random.choice(tuple(code for code in COUNTRIES if code != country))
                if suspicious and random.random() < 0.45
                else country,
                "is_high_risk_country": suspicious and random.random() < 0.35,
                "device_integrity_ok": False if suspicious and random.random() < 0.15 else True,
            }
        )

    return TransactionIn.model_validate(payload), suspicious


class ContinuousSimulator:
    """Generate and score synthetic transactions until the app shuts down."""

    def __init__(self, *, interval_seconds: float = 2.0, fraud_rate: float = 0.15) -> None:
        self.interval_seconds = max(interval_seconds, 0.1)
        self.fraud_rate = min(max(fraud_rate, 0.0), 1.0)
        self.scoring = ScoringService()
        self._records: deque[dict[str, Any]] = deque(maxlen=100)
        self._task: asyncio.Task[None] | None = None
        self._generated = 0
        self._scored = 0
        self._errors = 0
        self._counts = {"approve": 0, "review": 0, "decline": 0}
        self._channels = {"card": 0, "transfer": 0, "mobile": 0}
        self._suspicious_generated = 0
        self._suspicious_flagged = 0
        self._normal_flagged = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the single background producer if it is not already active."""
        if not self.running:
            self._task = asyncio.create_task(self._run(), name="continuous-transaction-simulator")

    async def stop(self) -> None:
        """Cancel and await the background producer during application shutdown."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            self._generated += 1
            try:
                transaction, suspicious = generate_transaction(self._generated, self.fraud_rate)
                scored = self.scoring.score(transaction)
                decision = scored.decision
                self._scored += 1
                self._counts[decision] += 1
                self._channels[transaction.channel] += 1
                if suspicious:
                    self._suspicious_generated += 1
                    if decision in {"review", "decline"}:
                        self._suspicious_flagged += 1
                elif decision in {"review", "decline"}:
                    self._normal_flagged += 1
                record = {
                    "transaction": transaction.model_dump(mode="json"),
                    "result": scored.model_dump(mode="json"),
                    "suspicious": suspicious,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                self._records.appendleft(record)
            except Exception as exc:  # Keep a transient synthetic-data failure from killing the loop.
                self._errors += 1
                self._records.appendleft(
                    {
                        "transaction": {"transaction_id": f"live-{self._generated:08d}"},
                        "error": str(exc),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            await asyncio.sleep(self.interval_seconds)

    def status(self) -> dict[str, Any]:
        """Return current producer status and aggregate decision counts."""
        return {
            "running": self.running,
            "interval_seconds": self.interval_seconds,
            "fraud_rate": self.fraud_rate,
            "generated": self._generated,
            "scored": self._scored,
            "errors": self._errors,
            "decisions": dict(self._counts),
            "channels": dict(self._channels),
            "suspicious_generated": self._suspicious_generated,
            "suspicious_flagged": self._suspicious_flagged,
            "normal_flagged": self._normal_flagged,
            "approval_rate": self._counts["approve"] / self._scored if self._scored else 0.0,
            "flagged_rate": (
                (self._counts["review"] + self._counts["decline"]) / self._scored
                if self._scored
                else 0.0
            ),
            "detection_rate": (
                self._suspicious_flagged / self._suspicious_generated
                if self._suspicious_generated
                else 0.0
            ),
        }

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return up to 100 most recent scored transaction records."""
        return list(self._records)[: min(max(limit, 1), 100)]


simulator = ContinuousSimulator()
