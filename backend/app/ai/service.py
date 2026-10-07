from typing import Any

from app.ai.provider import AIProvider, StubAIProvider


class AIAnalysisService:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self._provider = provider or StubAIProvider()

    async def run_analysis(self, context: dict[str, Any]) -> dict[str, Any]:
        return await self._provider.analyze(context)
