"""Transaction scoring endpoint."""

from fastapi import APIRouter, Depends

from app.api.deps import require_api_key
from app.schemas.transactions import ScoreResponse, TransactionIn
from app.services.scoring import ScoringService

router = APIRouter(prefix="/score", tags=["scoring"], dependencies=[Depends(require_api_key)])
_service = ScoringService()


@router.post("", response_model=ScoreResponse)
def score_transaction(transaction: TransactionIn) -> ScoreResponse:
    """Score one transaction and return its risk-based recommendation."""
    return _service.score(transaction)
