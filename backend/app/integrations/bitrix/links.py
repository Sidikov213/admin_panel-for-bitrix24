from app.core.config import get_settings

ACTIVITY_TYPES = {1: "Встреча", 2: "Звонок", 3: "Задача", 4: "Письмо", 6: "Сообщение"}


def deal_url(bitrix_id: int) -> str | None:
    """«Открыть в Bitrix» link, or None when BITRIX_PORTAL_URL is not set."""
    portal = get_settings().BITRIX_PORTAL_URL.rstrip("/")
    return f"{portal}/crm/deal/details/{bitrix_id}/" if portal else None


def activity_type_label(type_id: int | None) -> str:
    return ACTIVITY_TYPES.get(type_id or 0, "Дело")
