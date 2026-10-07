import hashlib
import json
from typing import Any


def compute_deal_content_hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
