from abc import ABC, abstractmethod
from typing import Any


class SLAReadOnlyAdapter(ABC):
    """Read-only SLA adapter interface — not implemented in Stage 1."""

    @abstractmethod
    async def get_sla_status(self, deal_external_id: str) -> dict[str, Any]:
        raise NotImplementedError


class SLAAdapterStub(SLAReadOnlyAdapter):
    async def get_sla_status(self, deal_external_id: str) -> dict[str, Any]:
        return {"status": "not_configured", "deal_id": deal_external_id}
