from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.targets import PeriodType
from app.schemas.common import ORMModel


class SalesTargetCreate(BaseModel):
    manager_id: int | None = None
    period_type: PeriodType
    period_start: date
    period_end: date
    amount: Decimal = Field(gt=0)
    currency: str = "RUB"


class SalesTargetUpdate(BaseModel):
    manager_id: int | None = None
    period_type: PeriodType | None = None
    period_start: date | None = None
    period_end: date | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None


class SalesTargetOut(ORMModel):
    id: int
    manager_id: int | None
    period_type: PeriodType
    period_start: date
    period_end: date
    amount: Decimal
    currency: str
