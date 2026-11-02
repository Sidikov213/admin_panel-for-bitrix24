from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.targets import PeriodType
from app.schemas.common import ORMModel

# A target longer than a year is almost certainly a typo in the dates
MAX_TARGET_DAYS = 366


class SalesTargetCreate(BaseModel):
    manager_id: int | None = None
    period_type: PeriodType
    period_start: date
    period_end: date
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="RUB", pattern=r"^[A-Z]{3}$")


class SalesTargetUpdate(BaseModel):
    manager_id: int | None = None
    period_type: PeriodType | None = None
    period_start: date | None = None
    period_end: date | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class SalesTargetOut(ORMModel):
    id: int
    manager_id: int | None
    period_type: PeriodType
    period_start: date
    period_end: date
    amount: Decimal
    currency: str
