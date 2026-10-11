"""Ensure Bitrix adapter exposes only read methods."""

import inspect

from app.integrations.bitrix import client as bitrix_mod
from app.integrations.bitrix.client import BitrixClient


def test_no_write_methods_on_client() -> None:
    names = [n for n, _ in inspect.getmembers(BitrixClient, predicate=inspect.isfunction)]
    forbidden = {"add", "update", "delete", "create", "set"}
    for name in names:
        lower = name.lower()
        for bad in forbidden:
            assert bad not in lower or name.startswith("_"), f"suspicious method: {name}"


def test_source_has_only_read_rest_calls() -> None:
    src = inspect.getsource(bitrix_mod)
    for write in (
        "crm.deal.add",
        "crm.deal.update",
        "crm.deal.delete",
        "crm.activity.add",
        "crm.activity.update",
        "crm.activity.delete",
    ):
        assert write not in src


def test_read_methods_list() -> None:
    # Document Bitrix REST read surface (incl. Manager Control Timeman)
    expected = {
        "crm.deal.list",
        "crm.deal.get",
        "crm.activity.list",
        "user.get",
        "user.search",
        "crm.dealcategory.list",
        "crm.dealcategory.stage.list",
        "crm.deal.fields",
        "timeman.status",
    }
    src = inspect.getsource(BitrixClient)
    for method in expected:
        assert method in src
    # Never allow write Timeman methods
    for write in ("timeman.open", "timeman.close", "timeman.pause", "timeman.settings.set"):
        assert write not in BitrixClient.ALLOWED_METHODS
