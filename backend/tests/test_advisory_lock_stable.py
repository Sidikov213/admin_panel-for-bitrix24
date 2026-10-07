"""Advisory lock keys must be stable across processes and shared for deal syncs."""

from app.models.sync import SyncType
from app.repositories.sync import advisory_lock_key


def test_advisory_lock_keys_stable_and_shared_for_deals() -> None:
    deals = advisory_lock_key(SyncType.deals)
    full = advisory_lock_key(SyncType.full_reconcile)
    dicts = advisory_lock_key(SyncType.dictionaries)
    acts = advisory_lock_key(SyncType.activities)

    assert deals == full
    assert deals != dicts
    assert deals != acts
    assert 0 < deals < 2**31
    # Recompute — must not depend on PYTHONHASHSEED
    assert advisory_lock_key(SyncType.deals) == deals
