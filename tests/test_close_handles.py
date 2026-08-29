"""R144 P2-5 — one taxonomy for driver-handle close failures.

The same event (a driver ``close()`` raising) previously had four outcomes
across the backends; redis was the silent ``contextlib.suppress`` outlier
with no diagnostic at all. ``backends._close.close_handles`` is the shared
outcome: suppressed ordinary failures reported through ``failed``, the
first control exception returned for exact re-raise, every handle attempted.
"""

from __future__ import annotations

import pytest

import scrapy_extension.backends.redis as redis_module
from scrapy_extension.backends._close import close_handles, swallow_close_failures
from scrapy_extension.backends.redis import RedisBackend


class _Handle:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.closed = False

    def close(self) -> None:
        self.closed = True
        if self.error is not None:
            raise self.error


class TestCloseHandles:
    def test_all_handles_closed_and_no_failures(self) -> None:
        first, second = _Handle(), _Handle()

        failed, control_error = close_handles(first, None, second)

        assert failed is False
        assert control_error is None
        assert first.closed and second.closed

    def test_ordinary_failure_is_reported_and_remaining_handles_close(self) -> None:
        failing = _Handle(RuntimeError("socket already closed"))
        survivor = _Handle()

        failed, control_error = close_handles(failing, survivor)

        assert failed is True
        assert control_error is None
        assert failing.closed and survivor.closed

    def test_control_exception_is_returned_and_remaining_handles_close(self) -> None:
        signal = KeyboardInterrupt("operator interrupt")
        interrupted = _Handle(signal)
        survivor = _Handle()

        failed, control_error = close_handles(interrupted, survivor)

        assert failed is False
        assert control_error is signal
        assert interrupted.closed and survivor.closed

    def test_swallow_close_failures_never_traps_control_exceptions(self) -> None:
        cleanup = swallow_close_failures()
        with pytest.raises(KeyboardInterrupt):
            with cleanup:
                raise KeyboardInterrupt("operator interrupt")
        assert cleanup.did_suppress is False

        with cleanup:
            raise RuntimeError("ordinary cleanup failure")
        assert cleanup.did_suppress is True


class TestRedisCloseHandlesAlignment:
    """Redis was the silent-suppression outlier (P2-5)."""

    def test_ordinary_close_failure_surfaces_a_diagnostic(self, mocker, caplog) -> None:
        failing = _Handle(RuntimeError("connection reset during close"))
        survivor = _Handle()
        debug_spy = mocker.patch.object(redis_module.logger, "debug")

        RedisBackend._close_handles(failing, survivor, None)  # must not raise

        assert failing.closed and survivor.closed
        debug_spy.assert_called_once_with("Suppressed redis cleanup error")

    def test_control_exception_is_reraised_after_all_handles_attempted(self) -> None:
        signal = KeyboardInterrupt("operator interrupt")
        interrupted = _Handle(signal)
        survivor = _Handle()

        with pytest.raises(KeyboardInterrupt) as excinfo:
            RedisBackend._close_handles(interrupted, survivor, None)

        assert excinfo.value is signal
        assert interrupted.closed and survivor.closed
