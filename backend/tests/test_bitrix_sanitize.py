from app.integrations.bitrix.sanitize import sanitize_bitrix_text, sanitize_bitrix_url, webhook_configured_label


def test_sanitize_bitrix_url_redacts_token() -> None:
    raw = "https://example.bitrix24.ru/rest/99999/secrettokenhere/crm.deal.list.json"
    out = sanitize_bitrix_url(raw)
    assert "secrettokenhere" not in out
    assert "19171" not in out
    assert "***/***" in out
    assert "example.bitrix24.ru" in out


def test_sanitize_bitrix_text_in_errors() -> None:
    msg = "HTTP error for https://focushouse.bitrix24.ru/rest/1/abc123xyz/crm.deal.list.json"
    out = sanitize_bitrix_text(msg)
    assert "abc123xyz" not in out
    assert "***/***" in out


def test_webhook_configured_label() -> None:
    assert webhook_configured_label("https://x/rest/1/t/") == "configured=true"
    assert webhook_configured_label("") == "configured=false"
