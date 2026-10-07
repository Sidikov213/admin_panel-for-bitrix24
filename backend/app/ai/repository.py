from typing import Any


class AIAnalysisRepository:
    """Stub persistence for AI analysis results — Stage 1."""

    async def save(self, deal_id: int, payload: dict[str, Any]) -> None:
        return None

    async def get_latest(self, deal_id: int) -> dict[str, Any] | None:
        return None
