"""One taxonomy for best-effort driver-handle close failures.

P2-5 (R144): the same event — a driver ``close()`` raising — had four
different outcomes across the ten backends (re-raise, swallow+typed error,
swallow+diagnostic, and redis's plain ``contextlib.suppress`` with no
diagnostic at all). This module is the shared discipline:

- ordinary close ``Exception``\\s are suppressed (a cleanup failure must
  never mask the caller's outcome) and *reported* — the caller emits a
  fixed diagnostic after the suppression has unwound;
- process-control exceptions (``KeyboardInterrupt`` / ``SystemExit`` /
  ``GeneratorExit``) are NEVER suppressed — :class:`swallow_close_failures`
  lets them propagate immediately, and :func:`close_handles` returns the
  first one so the caller can re-raise it exactly after finishing its own
  bookkeeping.
"""

from __future__ import annotations

from typing import Any

__all__ = ["close_handles", "swallow_close_failures"]


class swallow_close_failures:
    """Suppress regular cleanup errors and report that suppression to callers.

    ``__exit__`` deliberately does not log: it executes while the cleanup
    exception remains active in ``sys.exc_info()``.  The caller can inspect
    :attr:`did_suppress` after the ``with`` statement has unwound and emit
    static telemetry without exposing that exception to a logging handler.

    Only regular ``Exception``\\s are suppressed -- NEVER ``BaseException``
    (KeyboardInterrupt / SystemExit / GeneratorExit). Pre-fix the ancestors
    of this helper returned ``True`` for any non-None ``exc_type``, trapping
    Ctrl+C during close/disconnect (the operator's shutdown signal
    disappeared into a debug log).
    """

    def __init__(self) -> None:
        self.did_suppress = False

    def __enter__(self) -> swallow_close_failures:
        self.did_suppress = False
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is None:
            return False
        if not isinstance(exc, Exception):
            return False
        self.did_suppress = True
        return True


def close_handles(*clients: Any) -> tuple[bool, BaseException | None]:
    """Close every non-``None`` handle best-effort with one outcome.

    Ordinary close ``Exception``\\s are suppressed and reported through the
    ``failed`` flag (the caller decides its telemetry); the first
    process-control exception is returned — NOT raised — so the caller can
    finish closing the remaining handles and its own bookkeeping, then
    re-raise the exact signal.

    Args:
        *clients: Opaque driver handles to close; ``None`` entries are
            skipped. Callers deduplicate aliased handles before calling
            (identity semantics: each non-``None`` argument is closed once).

    Returns:
        ``(failed, control_error)``: ``failed`` is ``True`` when any
        ordinary close raised; ``control_error`` is the first
        process-control exception encountered, or ``None``.
    """
    failed = False
    control_error: BaseException | None = None
    for client in clients:
        if client is None:
            continue
        try:
            client.close()
        except Exception:
            failed = True
        except BaseException as error:
            if control_error is None:
                control_error = error
    return failed, control_error
