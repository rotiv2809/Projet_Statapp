from __future__ import annotations

import json
import logging
import os
from typing import Any

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging() -> None:
    root_logger = logging.getLogger()
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(_LOG_FORMAT)
    root_logger.setLevel(level)
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        return

    for handler in root_logger.handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    payload = {"event": event}
    payload.update({key: _json_safe(value) for key, value in fields.items()})
    logger.log(level, json.dumps(payload, ensure_ascii=False, sort_keys=True))
