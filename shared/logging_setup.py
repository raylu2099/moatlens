"""
Structured logging — JSON-lines to logs/moatlens.log + console pretty print.

Initialized once on web / CLI startup via setup_logging(). Safe to call
multiple times (idempotent).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


_initialized = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach extras from record
        for k, v in record.__dict__.items():
            if k in (
                "name", "msg", "args", "levelname", "levelno",
                "pathname", "filename", "module", "exc_info", "exc_text",
                "stack_info", "lineno", "funcName", "created", "msecs",
                "relativeCreated", "thread", "threadName", "processName",
                "process", "message",
            ):
                continue
            try:
                json.dumps(v)  # serializable?
                payload[k] = v
            except (TypeError, ValueError):
                payload[k] = repr(v)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[37m", "INFO": "\033[0m", "WARNING": "\033[33m",
        "ERROR": "\033[31m", "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now().strftime("%H:%M:%S")
        color = self.COLORS.get(record.levelname, "")
        extras = []
        for k, v in record.__dict__.items():
            if k in (
                "name", "msg", "args", "levelname", "levelno",
                "pathname", "filename", "module", "exc_info", "exc_text",
                "stack_info", "lineno", "funcName", "created", "msecs",
                "relativeCreated", "thread", "threadName", "processName",
                "process", "message",
            ):
                continue
            extras.append(f"{k}={v}")
        extras_str = f" [{', '.join(extras)}]" if extras else ""
        msg = f"{color}{ts} {record.levelname:7s}{self.RESET} {record.name}: {record.getMessage()}{extras_str}"
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return msg


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> None:
    """Set up JSON-to-file + pretty-to-stderr handlers on the root logger."""
    global _initialized
    if _initialized:
        return

    root = logging.getLogger()
    # Clear anything uvicorn/FastAPI may have added before us
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)

    # Console
    ch = logging.StreamHandler(stream=sys.stderr)
    ch.setFormatter(ConsoleFormatter())
    ch.setLevel(level)
    root.addHandler(ch)

    # File (rotating)
    if log_dir is None:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        log_dir / "moatlens.log",
        maxBytes=5 * 1024 * 1024,   # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    fh.setFormatter(JsonFormatter())
    fh.setLevel(level)
    root.addHandler(fh)

    # Calm noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    if not _initialized:
        setup_logging()
    return logging.getLogger(name)
