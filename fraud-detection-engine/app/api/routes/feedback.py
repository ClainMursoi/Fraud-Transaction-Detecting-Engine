"""Feedback endpoint for later model evaluation."""

from fastapi import APIRouter, Depends

from app.api.deps import require_api_key
from app.schemas.feedback import FeedbackIn, FeedbackOut

router = APIRouter(prefix="/feedback", tags=["feedback"], dependencies=[Depends(require_api_key)])


@router.post("", response_model=FeedbackOut, status_code=202)
def submit_feedback(feedback: FeedbackIn) -> FeedbackOut:
    """Acknowledge feedback; production deployments should persist it durably."""
    return FeedbackOut(transaction_id=feedback.transaction_id, label=feedback.label)
