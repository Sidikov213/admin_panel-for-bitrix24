"""Model access. The panel talks to the model only through `AIProvider.complete`."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

import anthropic
from pydantic import BaseModel

from app.core.config import get_settings

T = TypeVar("T", bound=BaseModel)

# Policy declines are re-run by the API on a suitable model inside the same call
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(Exception):
    """kind: not_configured | auth | rate_limit | unavailable | refusal | bad_output | limit"""

    def __init__(self, message: str, kind: str = "unavailable") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class AIResult(Generic[T]):
    output: T
    model: str
    input_tokens: int
    output_tokens: int


class AIProvider(ABC):
    @abstractmethod
    async def complete(self, *, system: str, prompt: str, schema: type[T]) -> AIResult[T]:
        raise NotImplementedError


class ClaudeProvider(AIProvider):
    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        s = get_settings()
        if client is None and not s.ai_configured:
            raise AIError("ИИ не подключён: не задан ANTHROPIC_API_KEY", "not_configured")
        self._model = s.AI_MODEL
        self._effort = s.AI_EFFORT
        # The key is passed explicitly: no fallback to other credential sources on the server
        self._client = client or anthropic.AsyncAnthropic(
            api_key=s.ANTHROPIC_API_KEY.strip(), timeout=s.AI_TIMEOUT_SECONDS, max_retries=2
        )

    async def complete(self, *, system: str, prompt: str, schema: type[T]) -> AIResult[T]:
        try:
            response = await self._client.beta.messages.parse(
                model=self._model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                output_config={"effort": self._effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise AIError("Anthropic отклонил ключ API", "auth") from e
        except anthropic.PermissionDeniedError as e:
            raise AIError("У ключа API нет доступа к этой модели", "auth") from e
        except anthropic.RateLimitError as e:
            raise AIError("Anthropic ограничил частоту запросов, попробуйте позже", "rate_limit") from e
        except anthropic.BadRequestError as e:
            raise AIError(f"Anthropic отклонил запрос: {e.message}", "bad_output") from e
        except anthropic.APIStatusError as e:
            raise AIError(f"Ошибка Anthropic {e.status_code}", "unavailable") from e
        except anthropic.APIConnectionError as e:
            raise AIError("Anthropic недоступен", "unavailable") from e
        except ValueError as e:
            # Invalid / cut JSON in the answer (pydantic.ValidationError is a ValueError)
            raise AIError("Ответ модели не совпал со схемой", "bad_output") from e

        if response.stop_reason == "refusal":
            raise AIError("Модель отказалась отвечать на запрос", "refusal")
        if response.stop_reason == "max_tokens":
            raise AIError("Ответ модели не уместился в лимит токенов", "bad_output")
        if response.parsed_output is None:
            raise AIError("Модель не вернула структурированный ответ", "bad_output")
        return AIResult(
            output=response.parsed_output,
            model=response.model,
            input_tokens=response.usage.input_tokens or 0,
            output_tokens=response.usage.output_tokens or 0,
        )
