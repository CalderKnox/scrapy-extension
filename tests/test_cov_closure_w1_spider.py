"""Coverage closure for BackendSpiderMixin lifecycle edges (w1 pack).

Each test targets a deterministic defensive branch of the mixin's lifecycle
machinery: orphan manager retries, signal-lease bookkeeping, the async
spider-opened offload, settings-surface tolerance helpers, and the
construction/close fences. No broker I/O — every manager is a stand-in.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from scrapy import Spider
from twisted.internet.defer import Deferred

from scrapy_extension.backends.base import BackendType
from scrapy_extension.backends.connectors import ConnectionManager
from scrapy_extension.spider import spider_mixin as spider_module
from scrapy_extension.spider.spider_mixin import BackendSpiderMixin


class _Spider(BackendSpiderMixin, Spider):
    name = "cov-closure-w1"
    backend_type = BackendType.REDIS


def _spider_with_manager(mocker: Any) -> tuple[_Spider, MagicMock]:
    """Return a bare spider whose manager slot holds a stand-in manager."""
    spider = _Spider()
    manager = mocker.MagicMock(spec=ConnectionManager)
    spider._connection_manager = manager
    return spider, manager


def test_release_orphan_managers_retains_failures_and_first_error(mocker: Any) -> None:
    spider, _manager = _spider_with_manager(mocker)
    assert spider._release_orphan_managers() is None

    released = MagicMock(name="released")
    released.close.return_value = None
    rejected = MagicMock(name="rejected")
    rejected.close.side_effect = RuntimeError("manager close failed")
    control = MagicMock(name="control")
    control.close.side_effect = KeyboardInterrupt("interrupted")
    spider._orphan_managers = [released, rejected, control]

    error = spider._release_orphan_managers()

    assert isinstance(error, RuntimeError)
    released.close.assert_called_once_with()
    rejected.close.assert_called_once_with()
    control.close.assert_called_once_with()
    # Failed owners stay reachable for the next close retry.
    assert spider._orphan_managers == [rejected, control]


def test_finish_orphan_lease_and_manager_dispatch_outcomes(mocker: Any) -> None:
    spider, _manager = _spider_with_manager(mocker)
    lease = MagicMock(name="lease")
    manager = MagicMock(name="manager")
    spider._orphan_leases = [lease]
    spider._orphan_managers = [manager]
    remembered: list[BaseException] = []

    spider._finish_orphan_lease(
        lease,
        spider_module.TwistedFailure(RuntimeError("lease release failed")),
        remembered.append,
    )
    assert isinstance(remembered[0], RuntimeError)
    assert spider._orphan_leases == [lease]
    remembered.clear()

    spider._finish_orphan_manager(
        manager,
        spider_module.TwistedFailure(RuntimeError("manager close failed")),
        remembered.append,
    )
    assert isinstance(remembered[0], RuntimeError)
    assert spider._orphan_managers == [manager]
    remembered.clear()

    spider._finish_orphan_lease(lease, None, remembered.append)
    spider._finish_orphan_manager(manager, None, remembered.append)
    assert not remembered
    assert spider._orphan_leases == []
    assert spider._orphan_managers == []


def test_on_spider_opened_offloads_connect_and_tracks_the_worker(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    spider, manager = _spider_with_manager(mocker)
    worker: Deferred[None] = Deferred()
    public: Deferred[None] = Deferred()
    ordered = MagicMock(name="ordered", return_value=(worker, public))
    monkeypatch.setattr(spider_module, "reactor_is_running", lambda: True)
    monkeypatch.setattr(spider_module, "defer_to_thread_ordered", ordered)

    result = spider._on_spider_opened(spider)

    assert result is public
    assert ordered.call_args[0][0] == manager.connect
    tracked = spider._async_component_operations
    assert list(tracked.values()) == [worker]
    worker.callback(None)
    assert not tracked


def test_on_spider_opened_swallows_connect_errback_adapter_failure(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _ErrbackRejectingOperation:
        called = False

        def addBoth(self, callback: Any) -> Any:
            return self

        def addErrback(self, callback: Any) -> Any:
            raise KeyboardInterrupt("errback adapter")

    spider, manager = _spider_with_manager(mocker)
    operation = _ErrbackRejectingOperation()
    public: Deferred[None] = Deferred()
    monkeypatch.setattr(spider_module, "reactor_is_running", lambda: True)
    monkeypatch.setattr(
        spider_module,
        "defer_to_thread_ordered",
        lambda *_args, **_kwargs: (operation, public),
    )

    assert spider._on_spider_opened(spider) is public
    assert list(spider._async_component_operations.values()) == [operation]


def test_on_spider_opened_connects_directly_without_a_reactor(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    spider, manager = _spider_with_manager(mocker)
    other = _Spider()
    assert spider._on_spider_opened(other) is None
    monkeypatch.setattr(spider_module, "reactor_is_running", lambda: False)
    assert spider._on_spider_opened(spider) is None
    manager.connect.assert_called_once_with()


def test_track_async_operation_double_attach_failure_pops_called_slot(
    mocker: Any,
) -> None:
    class _AdapterRejectingOperation:
        called = True

        def addBoth(self, callback: Any) -> Any:
            raise RuntimeError("addBoth adapter")

    spider, _manager = _spider_with_manager(mocker)
    spider._track_async_operation_locked("probe", _AdapterRejectingOperation())
    assert not spider._async_component_operations


def test_on_spider_closed_broken_logger_cannot_replace_the_close_result(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _BrokenLogger:
        def error(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("logging handler broke")

    spider, _manager = _spider_with_manager(mocker)
    close_deferred: Deferred[None] = Deferred()
    mocker.patch.object(spider, "close_backend", return_value=close_deferred)
    monkeypatch.setattr(spider_module, "logger", _BrokenLogger())

    observed = spider._on_spider_closed(spider, "finished")

    assert observed is close_deferred
    close_deferred.errback(RuntimeError("close failed"))
    assert close_deferred.called
    assert close_deferred.result is None


def test_component_settings_tolerates_a_raising_settings_surface() -> None:
    class _RaisingSettings:
        def get(self, key: Any, default: Any = None) -> Any:
            raise TypeError("settings surface broke")

    spider = _Spider()
    spider.crawler = SimpleNamespace(settings=_RaisingSettings())
    normalized = spider._component_settings()
    assert normalized.get("SCRAPY_QUEUE_STRATEGY") is None


def test_queue_factory_uses_shared_manager_tolerates_a_raising_settings_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RaisingSettings:
        def get(self, key: Any) -> Any:
            raise AttributeError("settings surface broke")

    monkeypatch.delenv("SCRAPY_QUEUE_BACKEND_TYPE", raising=False)
    monkeypatch.delenv("SCRAPY_BACKEND_TYPE", raising=False)
    spider = _Spider()
    assert spider._queue_factory_uses_shared_manager(_RaisingSettings()) is True


def test_construction_is_current_locks_and_delegates(mocker: Any) -> None:
    spider, manager = _spider_with_manager(mocker)
    construction = spider_module._ComponentConstruction(
        kind="queue",
        generation=spider._component_generation,
        owner_thread_id=threading.get_ident(),
    )
    spider._component_constructions["queue"] = construction

    assert spider._construction_is_current(construction, manager) is True
    replacement = mocker.MagicMock(spec=ConnectionManager)
    assert spider._construction_is_current(construction, replacement) is False


def test_request_close_after_construction_keeps_orphans_and_swallows_failures(
    mocker: Any,
) -> None:
    spider, _manager = _spider_with_manager(mocker)
    close = mocker.patch.object(spider, "close_backend")
    spider._orphan_leases = [MagicMock(name="lease")]
    assert spider._request_close_after_construction() is None
    close.assert_not_called()

    spider._orphan_leases = []
    close.side_effect = KeyboardInterrupt("shutdown")
    assert spider._request_close_after_construction() is None


def test_get_queue_async_without_a_reactor_is_immediate(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    spider, _manager = _spider_with_manager(mocker)
    monkeypatch.setattr(spider_module, "reactor_is_running", lambda: False)
    queue = MagicMock(name="queue")
    mocker.patch.object(spider, "get_queue", return_value=queue)

    succeeded = spider.get_queue_async()
    assert isinstance(succeeded, Deferred)
    assert succeeded.result is queue

    failures: list[Any] = []
    mocker.patch.object(spider, "get_queue", side_effect=RuntimeError("no backend"))
    failed = spider.get_queue_async()
    failed.addErrback(failures.append)
    assert isinstance(failures[0].value, RuntimeError)


def test_connect_signals_returns_when_the_aggregate_manager_unchanged() -> None:
    spider = _Spider()
    signal_manager = MagicMock(name="signal-manager")
    crawler = MagicMock()
    crawler.signals = signal_manager
    spider.crawler = crawler
    spider._signals_connected = True
    spider._connected_signals = signal_manager

    spider._connect_signals()

    signal_manager.connect.assert_not_called()


def test_disconnect_signals_broken_logger_is_advisory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenLogger:
        def error(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("logging handler broke")

    spider = _Spider()
    signal_manager = MagicMock(name="signal-manager")
    signal_manager.disconnect.side_effect = RuntimeError("provider broke")
    lease = spider_module._LifecycleSignalLease(
        signal_manager,
        spider._on_spider_opened,
        object(),
    )
    spider._signal_leases = [lease]
    monkeypatch.setattr(spider_module, "logger", _BrokenLogger())

    # Ordinary disconnect failure with strict=False stays advisory; the exact
    # lease is retained for the close-path retry.
    spider._disconnect_lifecycle_signals(signal_manager)

    signal_manager.disconnect.assert_called_once_with(lease.handler, lease.signal)
    assert spider._signal_leases == [lease]


def test_setup_backend_rejects_a_nonstring_resolved_backend_value() -> None:
    spider = _Spider()
    spider.backend_type = SimpleNamespace(value=12345)
    with pytest.raises(AssertionError):
        spider.setup_backend()


def test_setup_backend_resolves_a_lazily_computed_backend_value(mocker: Any) -> None:
    class _LazyBackendType:
        """backend_type whose ``value`` only settles after repeated probes."""

        def __init__(self) -> None:
            self.probes = 0

        @property
        def value(self) -> Any:
            self.probes += 1
            return None if self.probes < 3 else "redis"

    spider = _Spider()
    lazy = _LazyBackendType()
    spider.backend_type = lazy
    manager = mocker.MagicMock(spec=ConnectionManager)
    lease = mocker.MagicMock(name="lease")
    mocker.patch.object(ConnectionManager, "get_manager", return_value=manager)
    mocker.patch.object(
        ConnectionManager, "_adopt_latest_legacy_lease", return_value=lease
    )

    assert spider.setup_backend() is manager
    assert spider._connection_manager is manager
    assert spider._connection_manager_lease is lease
    assert lazy.probes >= 3
    spider.close_backend()


def test_get_scheduler_rejects_a_construction_invalidated_before_the_lock(
    mocker: Any,
) -> None:
    spider, _manager = _spider_with_manager(mocker)

    def invalidate_then_name() -> str:
        # A close between reservation and the publish check must invalidate
        # the generation instead of publishing onto the newer one.
        spider._component_generation += 1
        return "jobs"

    mocker.patch.object(spider, "_mixin_queue_key", side_effect=invalidate_then_name)
    with pytest.raises(RuntimeError, match="invalidated by close"):
        spider.get_scheduler()
    assert not spider._component_constructions


def test_close_after_construction_wait_returns_the_live_fence(mocker: Any) -> None:
    spider, _manager = _spider_with_manager(mocker)
    existing: Deferred[None] = Deferred()
    spider._close_wait_operation = existing
    spider._close_deferred = None
    result = spider._close_after_construction_wait((), (), threading.get_ident())
    assert result is existing


def test_get_dupefilter_tolerates_a_raising_settings_override_probe(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _SetProbeRaisingSettings:
        def get(self, key: Any, default: Any = None) -> Any:
            if key == "SCRAPY_SET_BACKEND_TYPE":
                raise TypeError("settings surface broke")
            return default

    spider, manager = _spider_with_manager(mocker)
    spider._mixin_project_name = "project"
    monkeypatch.delenv("SCRAPY_SET_BACKEND_TYPE", raising=False)
    monkeypatch.delenv("SCRAPY_BACKEND_TYPE", raising=False)
    mocker.patch.object(
        spider,
        "_component_settings",
        return_value=_SetProbeRaisingSettings(),
    )
    dupefilter = MagicMock(name="dupefilter")
    dupefilter.connection_manager = None
    mocker.patch(
        "scrapy_extension.dupefilter.dupefilter.BackendDupeFilter.from_settings",
        return_value=dupefilter,
    )

    assert spider.get_dupefilter() is dupefilter
    assert spider._dupefilter is dupefilter
    assert not spider._component_constructions
