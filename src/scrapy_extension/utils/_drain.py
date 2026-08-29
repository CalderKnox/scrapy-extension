"""Shared lifecycle-drain helpers for operation-accounted components.

P2-3 (R144): the queue close wait and the dupefilter quiescence wait drained
in-flight operations without a deadline — a hung backend call would wedge
close/clear forever. Both now use the drain shape audited as correct in
``backends/_generation.py``: control exceptions arriving during the wait are
remembered (never trapped — the authoritative drain completes, then the exact
signal is re-raised with its traceback scrubbed), and the wait itself is
bounded by an explicit deadline that escalates loudly to
:class:`BackendOperationTimeout`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import Condition

from scrapy_extension.exceptions import BackendOperationTimeout

__all__ = ["bounded_drain_wait"]


def bounded_drain_wait(
    condition: Condition,
    busy: Callable[[], bool],
    *,
    timeout_s: float,
    operation: str,
) -> None:
    """Wait under a held ``condition`` until ``busy()`` clears or the deadline.

    The caller must hold the condition's lock; this helper never releases it
    on return or raise (``Condition.wait`` re-acquires before propagating).
    ``busy`` is re-evaluated under the lock after every wake.

    Control exceptions (KeyboardInterrupt / SystemExit / GeneratorExit) raised
    inside ``Condition.wait`` are recorded and the drain continues — a signal
    never aborts an authoritative teardown — and the first recorded signal is
    re-raised, traceback scrubbed, once the drain completes. If the deadline
    passes first, :class:`BackendOperationTimeout` escalates instead.

    Args:
        condition: The guarding condition (the caller holds its lock).
        busy: Predicate evaluated under the lock; ``True`` means still
            draining.
        timeout_s: Wall-clock budget for the whole wait.
        operation: Static operation tag for the timeout error.
    """
    deadline = time.monotonic() + timeout_s
    control_error: BaseException | None = None
    while busy():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BackendOperationTimeout(operation, timeout_s)
        try:
            condition.wait(remaining)
        except BaseException as error:
            # Recorded, never trapped: the drain continues and the exact
            # signal is re-raised below once it completes.
            if control_error is None:
                control_error = error
    if control_error is not None:
        # The signal's traceback would otherwise retain this frame (and the
        # caller's locked state graph). Mirror the generation-gate scrub.
        control_error.__traceback__ = None
        control_error.__cause__ = None
        control_error.__context__ = None
        control_error.__suppress_context__ = True
        raise control_error
