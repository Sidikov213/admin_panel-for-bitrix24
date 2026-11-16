"""Bitrix answers ACTIVE as a boolean: reading it as "Y" marked working people as fired."""

from app.services.sync_service import bitrix_user_is_active


def test_active_flag_from_bitrix() -> None:
    assert bitrix_user_is_active({"ACTIVE": True}) is True
    assert bitrix_user_is_active({"ACTIVE": False}) is False
    assert bitrix_user_is_active({"ACTIVE": "Y"}) is True
    assert bitrix_user_is_active({"ACTIVE": "N"}) is False
    assert bitrix_user_is_active({}) is True
