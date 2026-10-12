"""
Structured logging setup for SZUP.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path

_cid: ContextVar[str] = ContextVar("szup_correlation_id", default="-")


def set_correlation_id(value: str) -> None:
    _cid.set(value or "-")


def get_correlation_id() -> str:
    return _cid.get()


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:16]


class _CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k in payload or k in _STD_ATTRS:
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except Exception:
                payload[k] = repr(v)
        return json.dumps(payload, ensure_ascii=False)


_STD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "correlation_id",
}


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_szup_configured", False):
        return

    level = getattr(logging, os.getenv("SZUP_LOG_LEVEL", "INFO").upper(), logging.INFO)
    root.setLevel(level)

    use_json = os.getenv("SZUP_LOG_JSON", "").lower() in ("1", "true", "yes")
    fmt: logging.Formatter = _JsonFormatter() if use_json else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(correlation_id)s]: %(message)s"
    )

    for h in list(root.handlers):
        root.removeHandler(h)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.addFilter(_CorrelationFilter())
    root.addHandler(sh)

    log_dir = Path(os.getenv("SZUP_LOG_DIR", "/opt/szup/logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        fh.addFilter(_CorrelationFilter())
        root.addHandler(fh)
    except Exception as e:
        logging.getLogger(__name__).warning("File logging disabled: %s", e)

    syslog = os.getenv("SZUP_SYSLOG_HOST")
    if syslog:
        try:
            host, _, port = syslog.partition(":")
            sys_h = logging.handlers.SysLogHandler(address=(host, int(port) if port else 514))
            sys_h.setFormatter(fmt)
            sys_h.addFilter(_CorrelationFilter())
            root.addHandler(sys_h)
        except Exception as e:
            logging.getLogger(__name__).warning("Syslog disabled: %s", e)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    root._szup_configured = True  # type: ignore[attr-defined]
