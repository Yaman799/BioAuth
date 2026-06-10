from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from .shared import QObject, Signal, Slot

LOGGER = logging.getLogger(__name__)
_LOG_THROTTLE_SEC = 5.0


class QtThreadDispatcher(QObject):
    """Queue narrow UI/refresh callables onto the Qt owner thread."""

    invokeRequested = Signal(object)

    def __init__(self, owner: Any | None = None) -> None:
        super().__init__()
        self._owner = owner
        self._main_thread_ident = threading.get_ident()
        self._last_log_at: dict[str, float] = {}
        try:
            self.invokeRequested.connect(self._invoke)
        except Exception:  # pragma: no cover - import-only Qt stubs
            pass

    def is_main_thread(self) -> bool:
        return threading.get_ident() == self._main_thread_ident

    def dispatch(self, callback: Callable[[], Any], *, target_action: str = "qt_thread_call") -> bool:
        called_from_non_main = not self.is_main_thread()
        self._log(target_action, called_from_non_main=called_from_non_main)
        if not called_from_non_main:
            callback()
            return True
        try:
            self.invokeRequested.emit(callback)
            return True
        except Exception:
            LOGGER.exception("qt_thread_dispatch emit failed", extra={"target_action": target_action})
            return False

    @Slot(object)
    def _invoke(self, callback: object) -> None:
        if callable(callback):
            callback()

    def _log(self, target_action: str, *, called_from_non_main: bool) -> None:
        now = time.monotonic()
        key = f"{target_action}:{called_from_non_main}"
        if now - float(self._last_log_at.get(key, 0.0) or 0.0) < _LOG_THROTTLE_SEC:
            return
        self._last_log_at[key] = now
        LOGGER.debug(
            "qt_thread_dispatch",
            extra={
                "current_thread_name": threading.current_thread().name,
                "target_action": target_action,
                "called_from_non_main_thread": called_from_non_main,
            },
        )


def install_qt_thread_dispatcher(owner: Any) -> QtThreadDispatcher:
    dispatcher = QtThreadDispatcher(owner)
    setattr(owner, "_qt_thread_dispatcher", dispatcher)
    setattr(owner, "_qt_main_thread_ident", dispatcher._main_thread_ident)
    return dispatcher


def is_qt_main_thread(owner: Any) -> bool:
    main_ident = getattr(owner, "_qt_main_thread_ident", None)
    if isinstance(main_ident, int):
        return threading.get_ident() == main_ident
    return threading.current_thread() is threading.main_thread()


def dispatch_to_qt_thread(owner: Any, callback: Callable[[], Any], *, target_action: str = "qt_thread_call") -> bool:
    dispatcher = getattr(owner, "_qt_thread_dispatcher", None)
    if isinstance(dispatcher, QtThreadDispatcher):
        return dispatcher.dispatch(callback, target_action=target_action)
    if is_qt_main_thread(owner):
        callback()
        return True
    LOGGER.warning(
        "qt_thread_dispatch_missing",
        extra={
            "current_thread_name": threading.current_thread().name,
            "target_action": target_action,
            "called_from_non_main_thread": True,
        },
    )
    return False
