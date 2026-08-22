"""Coverage-closure tests for connectors manager/config/plugin-contract paths.

Closes statement/branch gaps in ``backends/connectors/_manager.py``,
``backends/connectors/_config.py``, and ``backends/connectors/_plugin_contract.py``
that the existing suites leave cold: error-boundary rebuild paths, plugin
settings/constructor failure classification, registry-key input validation,
legacy lease-adoption drift, reactor timeout parsing, and the lazy backend
property's unpublished-backend contract. All backends are stubs or monkeypatched
loads; no network is touched.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from scrapy_extension.backends.base import Backend, QueueBackend
from scrapy_extension.backends.connectors import ConnectionManager
from scrapy_extension.backends.connectors import _config as config_mod
from scrapy_extension.backends.connectors import _manager as manager_mod
from scrapy_extension.backends.connectors import _plugin_contract as plugin_mod
from scrapy_extension.backends.registry import BackendDescriptor
from scrapy_extension.exceptions import (
    BackendConnectionError,
    ConfigurationError,
    QueueError,
)

# ---------------------------------------------------------------------------
# Module-level stubs (descriptor paths resolve module attributes lazily, so
# these mirror the tests/test_registry.py plugin-fixture pattern).
# ---------------------------------------------------------------------------


class _StubBackend(Backend, QueueBackend):
    """No-op bundled-behaviour stub accepted by the queue ACK snapshot."""

    requires_ack = False
    supports_concurrent_ack = False

    def __init__(self, settings: object | None = None) -> None:
        self.settings = settings

    @property
    def backend_type(self) -> str:
        return "plug"

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def is_connected(self) -> bool:
        return True

    def ping(self) -> bool:
        return True

    def push(self, queue_name: str, item: bytes, priority: float = 0.0) -> None:
        del queue_name, item, priority

    def pop(self, queue_name: str, timeout: float = 0.0) -> bytes | None:
        del queue_name, timeout
        return None

    def queue_len(self, queue_name: str) -> int:
        del queue_name
        return 0

    def clear_queue(self, queue_name: str) -> None:
        del queue_name


class _PlainSettings:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _ImportErrorSettings(_PlainSettings):
    def __init__(self, **kwargs: Any) -> None:
        del kwargs
        raise ImportError("optional dependency missing")


class _RuntimeErrorSettings(_PlainSettings):
    def __init__(self, **kwargs: Any) -> None:
        del kwargs
        raise RuntimeError("plugin settings renderer failed")


class _ImportErrorBackend(_StubBackend):
    def __init__(self, settings: object | None = None) -> None:
        del settings
        raise ImportError("optional dependency missing")


class _RuntimeErrorBackend(_StubBackend):
    def __init__(self, settings: object | None = None) -> None:
        del settings
        raise RuntimeError("plugin constructor failed")


def _plugin_descriptor() -> BackendDescriptor:
    return BackendDescriptor(
        "plug",
        "plug.Backend",
        "plug.Settings",
        frozenset({"storage"}),
    )


def _bundled_descriptor() -> BackendDescriptor:
    return BackendDescriptor(
        "redis",
        "redis.Backend",
        "redis.Settings",
        frozenset({"queue", "set", "storage"}),
    )


def _install_plugin(
    monkeypatch: pytest.MonkeyPatch, descriptor: BackendDescriptor, loader: Any
) -> None:
    monkeypatch.setattr(manager_mod, "get_descriptor", lambda _: descriptor)
    monkeypatch.setattr(plugin_mod, "_load_object", loader)


# ---------------------------------------------------------------------------
# _manager.py: safe connection diagnostics.
# ---------------------------------------------------------------------------


class TestSafeConnectionDiagnostics:
    def test_non_string_message_args_fall_back_to_static_message(self) -> None:
        error = BackendConnectionError(
            "Failed to connect after 1 attempt.", backend_type="redis"
        )
        error.args = (b"not-a-string",)
        assert (
            manager_mod._safe_manager_connection_message(error)
            == "Connection manager failed to connect to the selected backend."
        )

    def test_non_exact_error_and_plugin_backend_type_use_static_label(self) -> None:
        class _Subclassed(BackendConnectionError):
            pass

        subclassed = _Subclassed("detail", backend_type="redis")
        assert (
            manager_mod._safe_manager_connection_backend_type(subclassed)
            == "connection-manager"
        )

        plugin = BackendConnectionError("detail", backend_type="plug")
        assert (
            manager_mod._safe_manager_connection_backend_type(plugin)
            == "connection-manager"
        )

        no_backend_type = BackendConnectionError("Failed to connect after 2 attempts.")
        assert no_backend_type.backend_type is None
        assert (
            manager_mod._safe_manager_connection_backend_type(no_backend_type)
            == "connection-manager"
        )

    def test_multi_arg_configuration_error_rebuild_falls_back_to_generic(
        self,
    ) -> None:
        error = ConfigurationError("first", setting_name="second")
        error.args = ("first", "second")
        rebuilt = manager_mod._rebuild_connect_attempt_error(error)
        assert type(rebuilt) is ConfigurationError
        assert rebuilt.args[0] == "Connection manager configuration is invalid."
        assert rebuilt.setting_name == "configuration"

    def test_durable_push_boundary_rebuilds_queue_error_subclass_statically(
        self,
    ) -> None:
        class _QueueSubclass(QueueError):
            pass

        @manager_mod._durable_push_queue_error_boundary
        def push_through_plugin() -> None:
            raise _QueueSubclass("subclass detail with queue name")

        with pytest.raises(QueueError) as exc_info:
            push_through_plugin()
        assert type(exc_info.value) is QueueError
        assert exc_info.value.args[0] == "Queue backend push failed."


# ---------------------------------------------------------------------------
# _manager.py: registry key input validation and legacy lease adoption.
# ---------------------------------------------------------------------------


class TestRegistryKeyAndLegacyLease:
    @pytest.mark.parametrize(
        ("backend_type", "settings"),
        [
            (None, {}),
            ("redis", object()),
        ],
    )
    def test_registry_key_rejects_invalid_shapes(
        self, backend_type: object, settings: object
    ) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            ConnectionManager._registry_key(backend_type, settings)  # type: ignore[arg-type]
        assert (
            exc_info.value.args[0]
            == "Connection manager requires a backend registry-key string "
            "and settings dictionary."
        )
        assert exc_info.value.setting_name == "backend_settings"

    def test_adopt_latest_legacy_lease_skips_inactive_token_and_survives_drift(
        self,
    ) -> None:
        manager = ConnectionManager("redis")
        inactive_ghost = object()
        active_token = object()
        thread_id = threading.get_ident()
        manager._active_acquires = {active_token}
        manager._legacy_acquires = []  # drift: token active but absent from list
        # list.pop() consumes the tail first, so the inactive ghost leads and
        # the loop must fall through to the next candidate.
        manager._legacy_acquire_handoffs = {thread_id: [active_token, inactive_ghost]}

        lease = ConnectionManager._adopt_latest_legacy_lease(manager)

        assert lease is not None
        assert lease._token is active_token
        assert manager._legacy_acquire_handoffs == {}


# ---------------------------------------------------------------------------
# _manager.py: plugin / bundled backend construction failure classification.
# ---------------------------------------------------------------------------


class TestCreateBackendFailureClassification:
    def test_non_callable_plugin_classes_are_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_plugin(monkeypatch, _plugin_descriptor(), lambda _path: object())
        with pytest.raises(ConfigurationError) as exc_info:
            ConnectionManager("plug")._create_backend()
        assert (
            exc_info.value.args[0]
            == "Selected backend must provide callable backend and settings classes."
        )
        assert exc_info.value.setting_name == "SCRAPY_BACKEND_TYPE"

    def test_plugin_settings_import_error_is_typed_not_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        descriptor = _plugin_descriptor()

        def _load(path: str) -> object:
            return (
                _StubBackend
                if path == descriptor.backend_cls_path
                else _ImportErrorSettings
            )

        _install_plugin(monkeypatch, descriptor, _load)
        with pytest.raises(ConfigurationError) as exc_info:
            ConnectionManager("plug")._create_backend()
        assert exc_info.value.args[0] == "Invalid backend setting 'backend_settings'."
        assert exc_info.value.setting_name == "backend_settings"

    def test_plugin_backend_constructor_import_error_is_typed_not_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        descriptor = _plugin_descriptor()

        def _load(path: str) -> object:
            return (
                _ImportErrorBackend
                if path == descriptor.backend_cls_path
                else _PlainSettings
            )

        _install_plugin(monkeypatch, descriptor, _load)
        with pytest.raises(ConfigurationError) as exc_info:
            ConnectionManager("plug")._create_backend()
        assert exc_info.value.args[0] == "Selected backend could not be constructed."
        assert exc_info.value.setting_name == "SCRAPY_BACKEND_TYPE"

    def test_bundled_settings_runtime_error_is_reraised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        descriptor = _bundled_descriptor()

        def _load(path: str) -> object:
            return (
                _StubBackend
                if path == descriptor.backend_cls_path
                else _RuntimeErrorSettings
            )

        _install_plugin(monkeypatch, descriptor, _load)
        with pytest.raises(ConfigurationError) as exc_info:
            ConnectionManager("redis")._create_backend()
        assert exc_info.value.args[0] == "Connection manager configuration is invalid."

    def test_bundled_backend_constructor_runtime_error_is_reraised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        descriptor = _bundled_descriptor()

        def _load(path: str) -> object:
            return (
                _RuntimeErrorBackend
                if path == descriptor.backend_cls_path
                else _PlainSettings
            )

        _install_plugin(monkeypatch, descriptor, _load)
        with pytest.raises(ConfigurationError) as exc_info:
            ConnectionManager("redis")._create_backend()
        assert exc_info.value.args[0] == "Connection manager configuration is invalid."


# ---------------------------------------------------------------------------
# _manager.py: reactor io timeout parsing and lazy backend publication.
# ---------------------------------------------------------------------------


class TestReactorTimeoutAndLazyBackend:
    @pytest.mark.parametrize(
        "raw_timeout",
        [
            True,  # bool must never count as an int timeout
            61.0,  # above the finite manager budget
            0,  # non-positive
            "not-a-number",
        ],
    )
    def test_reactor_io_timeout_rejects_invalid_values(
        self, raw_timeout: object
    ) -> None:
        manager = ConnectionManager("redis", {"reactor_io_timeout": raw_timeout})
        with pytest.raises(ConfigurationError) as exc_info:
            manager._reactor_io_timeout()
        assert (
            exc_info.value.args[0]
            == "reactor_io_timeout must be finite and between 0 and 60 seconds"
        )
        assert exc_info.value.setting_name == "SCRAPY_REACTOR_IO_TIMEOUT"

    def test_lazy_backend_property_raises_when_connect_publishes_no_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = ConnectionManager("redis", {"retry_attempts": 0, "retry_delay": 0.0})

        def fake_connect() -> None:
            # A mocked/third-party connect() override that resolves the attempt
            # event without publishing a backend must surface the typed
            # contract error instead of returning None.
            assert manager._connect_attempt is not None
            manager._connect_attempt.event.set()

        monkeypatch.setattr(manager, "connect", fake_connect)
        with pytest.raises(BackendConnectionError) as exc_info:
            backend = manager.backend
        assert exc_info.value.args[0] == "connect() did not produce a backend"

    def test_retirement_during_lazy_connect_surfaces_release_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = ConnectionManager("redis", {"retry_attempts": 0, "retry_delay": 0.0})

        def retiring_connect() -> None:
            # The manager is retired while the lazy owner is inside connect():
            # the completed attempt must observe the release contract instead
            # of publishing a partially connected state.
            manager._retired = True

        monkeypatch.setattr(manager, "connect", retiring_connect)
        with pytest.raises(BackendConnectionError) as exc_info:
            backend = manager.backend
        assert (
            exc_info.value.args[0] == "Connection manager was released while connecting"
        )

    def test_reentrant_monitor_sees_retired_and_unpublished_states(self) -> None:
        manager = ConnectionManager("redis")
        attempt = manager_mod._ConnectionAttempt()
        manager._lazy_connection_context.dispatch_attempt = attempt

        manager._retired = True
        with pytest.raises(BackendConnectionError) as retired_case:
            manager._backend_from_reentrant_lazy_monitor()
        assert (
            retired_case.value.args[0]
            == "Connection manager was released while connecting"
        )

        manager._retired = False
        with pytest.raises(BackendConnectionError) as unpublished_case:
            manager._backend_from_reentrant_lazy_monitor()
        assert unpublished_case.value.args[0] == "connect() did not produce a backend"

    def test_connect_with_retries_refuses_released_manager_after_detach(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = ConnectionManager("redis")

        def detaching_then_released() -> tuple[None, None]:
            manager._retired = True
            return None, None

        monkeypatch.setattr(manager, "_detach_stale_backend", detaching_then_released)
        with pytest.raises(BackendConnectionError) as exc_info:
            manager._connect_with_retries([])
        assert exc_info.value.args[0] == "Cannot connect a released ConnectionManager"


# ---------------------------------------------------------------------------
# _plugin_contract.py: ACK snapshot, runtime contract, deferred-ack boundary.
# ---------------------------------------------------------------------------


class TestPluginContractBoundaries:
    def test_deferred_plugin_without_bool_concurrency_is_rejected(self) -> None:
        class _DeferredBadConcurrency(QueueBackend):
            requires_ack = True
            supports_concurrent_ack = "not-a-bool"

        descriptor = BackendDescriptor(
            "ackplug", "ackplug.Backend", "ackplug.Settings", frozenset({"queue"})
        )
        with pytest.raises(ConfigurationError) as exc_info:
            plugin_mod._validate_plugin_ack_class(descriptor, _DeferredBadConcurrency)
        assert (
            exc_info.value.args[0]
            == "Selected third-party queue backend has an invalid "
            "acknowledgement contract."
        )
        assert exc_info.value.setting_name == "SCRAPY_BACKEND_TYPE"

    def test_runtime_contract_reports_missing_backend_interface(self) -> None:
        descriptor = BackendDescriptor(
            "plug", "plug.Backend", "plug.Settings", frozenset()
        )
        with pytest.raises(ConfigurationError) as exc_info:
            plugin_mod._validate_backend_contract(object(), descriptor)
        assert (
            exc_info.value.args[0]
            == "Selected third-party backend does not implement its declared "
            "contract: missing Backend."
        )

    def test_deferred_ack_boundary_passes_control_exceptions_through(self) -> None:
        @plugin_mod._deferred_ack_queue_error_boundary("pop")
        def interrupted_delivery() -> None:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            interrupted_delivery()

    def test_deferred_ack_boundary_rebuilds_queue_error_subclass_generically(
        self,
    ) -> None:
        class _QueueSubclass(QueueError):
            pass

        @plugin_mod._deferred_ack_queue_error_boundary("pop")
        def plugin_delivery() -> None:
            raise _QueueSubclass("subclass detail with payload")

        with pytest.raises(QueueError) as exc_info:
            plugin_delivery()
        assert type(exc_info.value) is QueueError
        assert exc_info.value.args[0] == "Deferred-ack queue operation failed."


# ---------------------------------------------------------------------------
# _config.py: resolver loading, setting-name safety, flat-setting adaptation.
# ---------------------------------------------------------------------------


class TestConfigResolutionEdges:
    def test_plugin_settings_class_import_error_reraises_unwrapped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        descriptor = BackendDescriptor(
            "plug", "plug.Backend", "plug.Settings", frozenset({"storage"})
        )

        def _missing_dependency(_descriptor: object, _path: str) -> object:
            raise ImportError("optional dependency missing")

        monkeypatch.setattr(config_mod, "_load_descriptor_object", _missing_dependency)
        with pytest.raises(ImportError):
            config_mod._load_resolver_settings_class(descriptor)

    def test_exploding_plugin_error_renderer_falls_back_to_static_setting_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _exploding_errors(self: object) -> list[Any]:
            del self
            raise RuntimeError("plugin renderer failed")

        monkeypatch.setattr(ValidationError, "errors", _exploding_errors)
        error = ValidationError("model", [])
        assert (
            config_mod._safe_manager_setting_name(error, "redis", frozenset({"host"}))
            == "backend_settings"
        )

    def test_bundled_model_without_env_prefix_skips_flat_extraction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _NoPrefixModel(BaseModel):
            model_config = {"env_prefix": ""}

        monkeypatch.setattr(
            config_mod, "_load_resolver_settings_class", lambda _d: _NoPrefixModel
        )
        merged = config_mod._adapt_backend_settings(
            {"SCRAPY_REDIS_HOST": "flat.example.com"}, "redis", {}
        )
        assert "host" not in merged

    def test_flat_keys_are_read_from_non_mapping_settings_objects(self) -> None:
        class _SettingsLike:
            """Non-Mapping settings surface exposing only ``get``."""

            def __init__(self, values: dict[str, Any]) -> None:
                self._values = values

            def get(self, name: str, default: object = None) -> object:
                return self._values.get(name, default)

        merged = config_mod._adapt_backend_settings(
            _SettingsLike({"SCRAPY_REDIS_HOST": "redis-like.example.com"}),
            "redis",
            {},
        )
        assert merged["host"] == "redis-like.example.com"
