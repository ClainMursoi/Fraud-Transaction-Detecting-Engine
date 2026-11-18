"""Schemas for post-decision feedback."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1, max_length=128)
    label: Literal["fraud", "legitimate"]
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackOut(BaseModel):
    transaction_id: str
    label: Literal["fraud", "legitimate"]
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "accepted"
