"""Read-only status and feed for the built-in synthetic transaction producer."""

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_api_key
from app.services.simulator import simulator

router = APIRouter(
    prefix="/simulator",
    tags=["simulator"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/status")
def simulator_status() -> dict[str, object]:
    """Return whether the continuous synthetic transaction producer is active."""
    return simulator.status()


@router.get("/transactions")
def simulator_transactions(limit: int = Query(default=50, ge=1, le=100)) -> dict[str, object]:
    """Return the latest transactions generated and scored by this app process."""
    return {"items": simulator.recent(limit), "status": simulator.status()}
