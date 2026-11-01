import json
import logging
import sys
import re
import traceback
from datetime import datetime, timezone
from typing import Any
from app.integrations.bitrix.sanitize import sanitize_bitrix_text


def redact(text: str) -> str:
    text = sanitize_bitrix_text(text)
    text = re.sub(r"(?i)(bearer\s+)[^\s,;\"']+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:password|passwd|secret|access_token|refresh_token|client_secret|authorization|cookie)\s*[\"']?\s*[:=]\s*[\"']?)[^\s,;\"'}]+", r"\1[REDACTED]", text)
    return re.sub(r"(://[^:/\s]+:)[^@\s]+(@)", r"\1[REDACTED]\2", text)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if record.exc_info:
            # Exception strings (especially SQLAlchemy) may contain full SQL
            # parameters/customer data. Keep type and source frames only.
            payload["exception"] = {
                "type": record.exc_info[0].__name__,
                "frames": [{"file": f.filename, "line": f.lineno, "function": f.name}
                           for f in traceback.extract_tb(record.exc_info[2])],
            }
        for key in ("request_id", "user_id", "sync_type"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
