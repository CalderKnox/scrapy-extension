"""R144 P2-3 — deadline-bounded lifecycle drains and lease reconciliation.

The queue close wait and the dupefilter quiescence wait previously drained
in-flight operations without a deadline (a hung backend call wedged
close/clear forever), and the queue released its per-thread operation lease
in a two-step decrement that an interrupt could desynchronize. These pins
hold the shared bounded-drain helper, the reconciled per-thread lease
accounting, and the loud timeout escalation at both lifecycle seams.
"""

from __future__ import annotations

import threading
from threading import Condition, Thread

import pytest

from scrapy_extension.dupefilter.dupefilter import BackendDupeFilter
from scrapy_extension.exceptions import BackendOperationTimeout
from scrapy_extension.queue.queue import BackendQueue
from scrapy_extension.utils._drain import bounded_drain_wait


class TestBoundedDrainWait:
    def test_clears_immediately_without_waiting(self) -> None:
        condition = Condition()

        with condition:
            bounded_drain_wait(
                condition, lambda: False, timeout_s=1.0, operation="test-drain"
            )

    def test_deadline_escalates_to_loud_timeout(self) -> None:
        condition = Condition()

        with condition:
            with pytest.raises(BackendOperationTimeout) as excinfo:
                bounded_drain_wait(
                    condition,
                    lambda: True,
                    timeout_s=0.05,
                    operation="test-drain",
                )
        assert "test-drain" in str(excinfo.value)

    def test_control_signal_is_preserved_and_reRaised_after_drain(self) -> None:
        condition = Condition()
        signal = KeyboardInterrupt("operator interrupt")

        class _SignallingCondition(Condition):
            def wait(self, timeout=None):
                # The signal arrives mid-drain; the drain must continue and
                # re-raise the exact signal once the predicate clears.
                raise signal

        signalling = _SignallingCondition()
        busy_calls = [0]

        def busy() -> bool:
            busy_calls[0] += 1
            return busy_calls[0] == 1

        with signalling:
            with pytest.raises(KeyboardInterrupt) as excinfo:
                bounded_drain_wait(
                    signalling, busy, timeout_s=2.0, operation="test-drain"
                )
        # Exact control object with its context chain scrubbed (a re-raise
        # always attaches a fresh minimal traceback of its own).
        assert excinfo.value is signal
        assert signal.__context__ is None
        assert signal.__cause__ is None
        assert busy_calls[0] == 2


class TestQueueLeaseReconciliation:
    def test_per_thread_leases_reconcile_in_one_gate_section(
        self, mock_connection_manager, mock_spider
    ) -> None:
        queue = BackendQueue(
            connection_manager=mock_connection_manager,
            queue_name="test_queue",
            spider=mock_spider,
        )

        queue._begin_operation("one")
        queue._begin_operation("two")
        assert queue._close_called_from_active_operation() is True

        queue._end_operation()
        # One lease still owned by this thread after the nested release.
        assert queue._close_called_from_active_operation() is True
        assert queue._active_operations == 1
        assert threading.get_ident() in queue._active_operation_threads

        queue._end_operation()
        assert queue._close_called_from_active_operation() is False
        assert queue._active_operations == 0
        assert queue._active_operation_threads == {}

    def test_close_drain_escalates_on_hung_operation(
        self, mock_connection_manager, mock_spider
    ) -> None:
        queue = BackendQueue(
            connection_manager=mock_connection_manager,
            queue_name="test_queue",
            spider=mock_spider,
            reactor_io_timeout=0.1,
        )
        queue._begin_operation("hung")
        close_error: list[BaseException] = []

        def close() -> None:
            try:
                queue.close()
            except BaseException as error:  # pragma: no cover - capture aid
                close_error.append(error)

        closer = Thread(target=close)
        closer.start()
        closer.join(timeout=5.0)
        assert not closer.is_alive()

        # The hung lease escalates loudly instead of wedging close forever.
        assert len(close_error) == 1
        assert isinstance(close_error[0], BackendOperationTimeout)

        # Releasing the lease lets a retry close drain normally.
        queue._end_operation()
        assert queue._active_operations == 0


class TestDupefilterQuiescenceDeadline:
    def test_quiescence_drain_escalates_on_hung_admitted_call(
        self, mock_connection_manager
    ) -> None:
        dupefilter = BackendDupeFilter(
            connection_manager=mock_connection_manager,
            drain_timeout_s=0.1,
        )
        admitted = threading.Event()
        release = threading.Event()
        holder_error: list[BaseException] = []

        def hold_admitted_call() -> None:
            admission = dupefilter._admit_operation("request_seen")
            entered = False
            try:
                admission.__enter__()
                entered = True
                admitted.set()
                assert release.wait(timeout=5.0)
            except BaseException as error:  # pragma: no cover - capture aid
                holder_error.append(error)
            finally:
                if entered:
                    admission.__exit__(None, None, None)

        holder = Thread(target=hold_admitted_call)
        holder.start()
        assert admitted.wait(timeout=5.0)

        with dupefilter._lifecycle_condition:
            with pytest.raises(BackendOperationTimeout) as excinfo:
                dupefilter._wait_for_quiescence_locked(include_reservations=False)
        assert "dupefilter-quiescence" in str(excinfo.value)

        release.set()
        holder.join(timeout=5.0)
        assert holder_error == []
        assert dupefilter._active_operations == 0
