from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class StageBrief(ORMModel):
    id: int
    name: str
    bitrix_id: str
    semantics: str | None = None


class ManagerBrief(ORMModel):
    id: int
    name: str
    last_name: str
    bitrix_id: int
    is_active: bool = True


class DealOut(ORMModel):
    id: int
    bitrix_id: int
    title: str
    category_id: int | None
    stage_id: int | None
    assigned_by_id: int | None
    opportunity: Decimal | None
    currency_id: str | None
    date_create: datetime | None
    date_modify: datetime | None
    closedate: datetime | None
    closed: bool
    has_future_activity: bool
    open_activities_count: int
    next_deadline_at: datetime | None
    last_observed_activity_at: datetime | None
    stage_changed_observed_at: datetime | None = None
    observed_at: datetime | None = None
    stage: StageBrief | None = None
    assigned_manager: ManagerBrief | None = None


class ActivityOut(ORMModel):
    id: int
    bitrix_id: int
    type_id: int | None
    subject: str | None
    responsible_id: int | None
    owner_type_id: int | None
    owner_id: int | None
    created: datetime | None
    deadline: datetime | None
    completed: bool
    completed_at: datetime | None


class ChangeEventOut(BaseModel):
    id: int
    deal_id: int
    field_name: str
    old_value: str | None
    new_value: str | None
    observed_at: datetime
    bitrix_event_at: datetime | None
    note: str | None = None


class TimelineItem(BaseModel):
    at: datetime
    kind: str
    title: str
    detail: str | None = None
    is_observed: bool = True
    note: str | None = None


class SnapshotOut(BaseModel):
    id: int
    observed_at: datetime
    content_hash: str
    payload_summary: dict | None = None


class DealDetailOut(DealOut):
    activities: list[ActivityOut] = Field(default_factory=list)
    current_activities: list[ActivityOut] = Field(default_factory=list)
    overdue_activities: list[ActivityOut] = Field(default_factory=list)
    future_activities: list[ActivityOut] = Field(default_factory=list)
    change_events: list[ChangeEventOut] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)
    snapshots: list[SnapshotOut] = Field(default_factory=list)
    pipeline_name: str | None = None
    no_future_activity_label: str | None = None
    bitrix_url: str | None = None
    hours_without_observed_movement: float | None = None
    violations: dict | None = None


class DealListResponse(BaseModel):
    items: list[DealOut]
    total: int
    offset: int
    limit: int
