from __future__ import annotations

import logging
from contextvars import ContextVar, Token


_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        record.trace_id = _trace_id_var.get()
        return True


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=(
            "%(asctime)s %(levelname)s %(name)s "
            "request_id=%(request_id)s trace_id=%(trace_id)s %(message)s"
        ),
        force=True,
    )
    context_filter = RequestContextFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(context_filter)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def set_request_id(request_id: str) -> Token[str]:
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _request_id_var.reset(token)


def set_trace_id(trace_id: str | None) -> Token[str]:
    return _trace_id_var.set(trace_id or "-")


def reset_trace_id(token: Token[str]) -> None:
    _trace_id_var.reset(token)


def get_request_id() -> str:
    return _request_id_var.get()


def get_trace_id() -> str:
    return _trace_id_var.get()
