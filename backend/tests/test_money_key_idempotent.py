from decimal import Decimal

from app.services.sync_service import _money_key


def test_money_key_normalizes_bitrix_scale() -> None:
    assert _money_key("229320.00000000") == _money_key(Decimal("229320.00"))
    assert _money_key("0E-8") == _money_key("0.00")
    assert _money_key(None) is None
