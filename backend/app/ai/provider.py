from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    @abstractmethod
    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class StubAIProvider(AIProvider):
    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"summary": "AI analysis not configured", "context_keys": list(context.keys())}
