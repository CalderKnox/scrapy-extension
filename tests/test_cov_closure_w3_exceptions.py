"""Coverage closure for exception redaction and settings sanitization (w3 pack).

Closes the remaining cold defensive branches of the exception redaction layer:
message/type guards, forced value collection, undecodable-bytes fail-closed
paths, whitespace-needle skips, the redacting setting-value copier, operation
rebuilds through ``sanitize_backend_error``, and the fail-closed boundary
predicates. Everything runs on pure Python objects — no I/O.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from scrapy_extension.exceptions import (
    BackendConnectionError,
    BackendError,
    ConfigurationError,
    QueueError,
    QueueOutcomeIndeterminateError,
    SerializationError,
    SetOutcomeIndeterminateError,
    StorageError,
    StorageOutcomeIndeterminateError,
)
from scrapy_extension.exceptions._redaction import (
    backend_connection_error_boundary,
    sanitize_backend_error,
    set_operation_error_boundary,
    storage_operation_error_boundary,
)
from scrapy_extension.exceptions.base import (
    _redact_message,
    _redact_setting_value,
    _safe_diagnostic_label,
    _safe_setting_name,
)
from scrapy_extension.settings._redacted import (
    _CanonicalScalarEnvironmentSource,
    _redacted_validation_error,
    _safe_location,
    _scalar_annotation_kind,
    _secret_annotation_kind,
    _trusted_settings_fields,
)
from scrapy_extension.settings.redis import RedisSettings

# ---------------------------------------------------------------------------
# exceptions/base.py — message redaction guards
# ---------------------------------------------------------------------------


def test_redact_message_rejects_non_string_message() -> None:
    assert _redact_message(b"not-text") == "Invalid configuration."


def test_redact_message_forced_collection_covers_plain_and_whitespace_values() -> None:
    # A forced ordinary value is still collected as a needle.
    assert (
        _redact_message(
            "bind to ordinary-value now", "ordinary-value", force_setting_value=True
        )
        == "bind to ***REDACTED*** now"
    )
    # Whitespace-only needles carry no secret material and are skipped.
    assert _redact_message("keep this text", "  ", force_setting_value=True) == (
        "keep this text"
    )


def test_redact_message_fails_closed_on_undecodable_bytes() -> None:
    assert _redact_message("m", b"\xff\xfe", force_setting_value=True) == (
        "Invalid configuration."
    )


def test_safe_diagnostic_label_and_setting_name_guards() -> None:
    assert _safe_diagnostic_label("queue_depth") == "queue_depth"
    assert _safe_diagnostic_label(12345) is None

    assert _safe_setting_name("some_marker_field") is None
    assert _safe_setting_name("hosts") == "hosts"


def test_redact_setting_value_fail_closed_paths() -> None:
    # An omitted sensitive field without a uri/url fragment is redacted.
    assert _redact_setting_value(None, "password") == "***REDACTED***"
    # Undecodable bytes never survive as a diagnostic value.
    assert _redact_setting_value(b"\xff\xfe", "note") == "***REDACTED***"
    # Decodable but credential-shaped bytes are redacted.
    assert _redact_setting_value(b"authorization: Bearer abc", "note") == (
        "***REDACTED***"
    )

    class _HostileMapping(dict):  # type: ignore[type-arg]
        def items(self) -> Any:
            raise RuntimeError("hostile items()")

    assert _redact_setting_value(_HostileMapping(), "note") == "***REDACTED***"


# ---------------------------------------------------------------------------
# exceptions/_redaction.py — operation rebuilds and fail-closed predicates
# ---------------------------------------------------------------------------


def test_sanitize_backend_error_queue_operation_rebuilds() -> None:
    indeterminate = sanitize_backend_error(
        QueueOutcomeIndeterminateError("x", operation="pop"),
        message="replaced",
        safe_queue_operations={"pop"},
    )
    assert isinstance(indeterminate, QueueOutcomeIndeterminateError)
    assert indeterminate.operation == "pop"

    with_fallback = sanitize_backend_error(
        QueueError("x", operation="weird"),
        message="replaced",
        safe_queue_operations={"pop"},
        fallback_queue_operation="pop",
    )
    assert isinstance(with_fallback, QueueError)
    assert with_fallback.operation == "pop"

    without_fallback = sanitize_backend_error(
        QueueError("x", operation="weird"),
        message="replaced",
        safe_queue_operations={"pop"},
        fallback_queue_operation="not-listed",
    )
    assert isinstance(without_fallback, QueueError)
    assert without_fallback.operation is None


def test_sanitize_backend_error_storage_operation_rebuilds() -> None:
    indeterminate = sanitize_backend_error(
        StorageOutcomeIndeterminateError("x", operation="set"),
        message="replaced",
        safe_storage_operations={"set"},
    )
    assert isinstance(indeterminate, StorageOutcomeIndeterminateError)
    assert indeterminate.operation == "set"

    with_fallback = sanitize_backend_error(
        StorageError("x", operation="weird"),
        message="replaced",
        safe_storage_operations={"set"},
        fallback_storage_operation="set",
    )
    assert isinstance(with_fallback, StorageError)
    assert with_fallback.operation == "set"

    without_fallback = sanitize_backend_error(
        StorageOutcomeIndeterminateError("x", operation="weird"),
        message="replaced",
        safe_storage_operations={"set"},
        fallback_storage_operation="not-listed",
    )
    assert isinstance(without_fallback, StorageOutcomeIndeterminateError)
    assert without_fallback.operation is None


def test_sanitize_backend_error_connection_and_plain_family_rebuilds() -> None:
    assert isinstance(
        sanitize_backend_error(SetOutcomeIndeterminateError("x"), message="replaced"),
        SetOutcomeIndeterminateError,
    )
    assert isinstance(
        sanitize_backend_error(BackendConnectionError("x"), message="replaced"),
        BackendConnectionError,
    )
    assert isinstance(
        sanitize_backend_error(SerializationError("x"), message="replaced"),
        SerializationError,
    )
    assert isinstance(
        sanitize_backend_error(ConfigurationError("x"), message="replaced"),
        ConfigurationError,
    )
    assert type(sanitize_backend_error(BackendError("x"), message="replaced")) is (
        BackendError
    )

    class _SecondAllocationHostile(BackendError):
        allocations = 0

        def __new__(cls, *args: Any) -> Any:
            cls.allocations += 1
            if cls.allocations > 1:
                raise RuntimeError("allocation is hostile")
            return super().__new__(cls)

    collapsed = sanitize_backend_error(
        _SecondAllocationHostile("x"), message="replaced"
    )
    assert type(collapsed) is BackendError


def test_set_operation_boundary_rebuilds_indeterminate_outcomes() -> None:
    @set_operation_error_boundary("set failed", "redis")
    def operate() -> None:
        raise SetOutcomeIndeterminateError("opaque driver failure")

    with pytest.raises(SetOutcomeIndeterminateError, match="set failed"):
        operate()


def test_storage_boundary_predicate_failures_fall_closed() -> None:
    def _raising_predicate(message: str) -> bool:
        raise RuntimeError("predicate broke")

    @storage_operation_error_boundary(
        "get failed", "storage down", "redis", safe_message_predicate=_raising_predicate
    )
    def read() -> None:
        raise StorageError("opaque driver failure")

    with pytest.raises(StorageError, match="storage down"):
        read()


def test_connection_boundary_predicate_failures_fall_closed() -> None:
    def _raising_predicate(message: str) -> bool:
        raise RuntimeError("predicate broke")

    @backend_connection_error_boundary(
        "connect failed", "redis", safe_message_predicate=_raising_predicate
    )
    def connect() -> None:
        raise BackendConnectionError("opaque driver failure")

    with pytest.raises(BackendConnectionError, match="connect failed"):
        connect()


# ---------------------------------------------------------------------------
# settings/_redacted.py — safe locations, annotations, sources
# ---------------------------------------------------------------------------


def test_safe_location_keeps_integer_path_segments() -> None:
    assert _safe_location(("hosts", 1, "nested"), frozenset({"hosts"})) == (
        "hosts",
        1,
        "value",
    )
    assert _safe_location(None, frozenset({"hosts"})) == ("configuration",)
    assert _safe_location(("weird",), frozenset({"hosts"})) == ("configuration",)


def test_redacted_validation_error_rebuilds_without_diagnostics() -> None:
    from pydantic import BaseModel, ValidationError

    class _Port(BaseModel):
        port: int

    try:
        _Port(port="not-a-port")
    except ValidationError as error:
        rebuilt = _redacted_validation_error(error, frozenset({"port"}))
        assert [detail["loc"] for detail in rebuilt.errors()] == [("port",)]


def test_trusted_settings_fields_reject_foreign_models() -> None:
    assert _trusted_settings_fields(BaseSettings) is None
    assert _trusted_settings_fields(RedisSettings) is not None


def test_annotation_kind_unwraps_annotated_and_optional_forms() -> None:
    from typing import Annotated

    assert _secret_annotation_kind(Annotated[SecretStr, "meta"]) == (SecretStr, False)
    assert _secret_annotation_kind(SecretStr | None) == (SecretStr, True)
    assert _secret_annotation_kind(Annotated[str, "meta"]) is None

    assert _scalar_annotation_kind(Annotated[int, "meta"]) == (int, False)
    assert _scalar_annotation_kind(int | None) == (int, True)
    assert _scalar_annotation_kind(SecretStr) is None


class _StubEnvironmentSource(PydanticBaseSettingsSource):
    """Minimal source whose lookup and call behaviour is test-controlled."""

    def __init__(self, settings_cls: type[BaseSettings], values: object) -> None:
        super().__init__(settings_cls)
        self.values = values
        self.lookups: list[str] = []

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        self.lookups.append(field_name)
        return self._source_value(field, field_name)

    def _source_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> object:
        if isinstance(self.values, BaseException):
            raise self.values
        return self.values


def test_canonical_scalar_source_delegates_field_lookup() -> None:
    stub = _StubEnvironmentSource(RedisSettings, {})
    canonical = _CanonicalScalarEnvironmentSource(RedisSettings, stub)

    class _Field:
        annotation = int | None

    value, name, is_complex = canonical.get_field_value(_Field(), "db")

    assert (value, name, is_complex) == (None, "db", False)
    assert stub.lookups == ["db"]


def test_canonical_scalar_source_returns_non_mapping_values_verbatim() -> None:
    stub = _StubEnvironmentSource(RedisSettings, ["not", "a", "mapping"])
    canonical = _CanonicalScalarEnvironmentSource(RedisSettings, stub)
    assert canonical() == ["not", "a", "mapping"]


class _RaisingSettings(RedisSettings):
    _source_failure: BaseException | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        failure = cls._source_failure
        assert failure is not None
        return (_StubEnvironmentSource(cls, failure),)


def test_settings_init_sanitizes_source_and_unexpected_failures() -> None:
    from pydantic_settings import SettingsError

    _RaisingSettings._source_failure = SettingsError("opaque")
    with pytest.raises(ConfigurationError, match="source contains"):
        _RaisingSettings()

    _RaisingSettings._source_failure = RuntimeError("opaque")
    with pytest.raises(ConfigurationError, match="invalid configuration value"):
        _RaisingSettings()


class _ConfigurationSubclassError(ConfigurationError):
    pass


class _RaisingConfigurationSettings(RedisSettings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (_StubEnvironmentSource(cls, _ConfigurationSubclassError("opaque")),)


def test_settings_init_sanitizes_configuration_error_subclasses() -> None:
    with pytest.raises(ConfigurationError, match="invalid configuration value"):
        _RaisingConfigurationSettings()


class _BrokenMetadataSettings(RedisSettings):
    pass


class _HostileAnnotationField(FieldInfo):
    def __init__(self) -> None:
        self._annotation: Any = None
        super().__init__()

    @property
    def annotation(self) -> Any:  # type: ignore[override]
        raise RuntimeError("field metadata is hostile")

    @annotation.setter
    def annotation(self, value: Any) -> None:
        self._annotation = value


def test_setattr_tolerates_hostile_model_metadata() -> None:
    settings = _BrokenMetadataSettings()
    # Poison field metadata after construction; the assignment boundary must
    # still publish the plain value instead of crashing on the hostile lookup.
    _BrokenMetadataSettings.model_fields = {"host": _HostileAnnotationField()}  # type: ignore[assignment]
    settings.host = "redis.internal"
    assert settings.host == "redis.internal"


# ---------------------------------------------------------------------------
# w3 extension — remaining fail-closed guards
# ---------------------------------------------------------------------------

_validator_failure: BaseException | None = None


class _ValidatingSettings(RedisSettings):
    @field_validator("host")
    @classmethod
    def _raise_injected_failure(cls, value: object) -> object:
        if _validator_failure is not None:
            raise _validator_failure
        return value


def test_model_validate_sanitizes_unexpected_validator_failures() -> None:
    global _validator_failure
    _validator_failure = RuntimeError("opaque validator failure")
    with pytest.raises(ConfigurationError, match="invalid configuration value"):
        _ValidatingSettings.model_validate({"host": "localhost"})

    _validator_failure = _ConfigurationSubclassError("opaque typed failure")
    with pytest.raises(ConfigurationError, match="invalid configuration value"):
        _ValidatingSettings.model_validate({"host": "localhost"})

    _validator_failure = None


class _GhostModuleSettings(RedisSettings):
    pass


def test_trusted_settings_fields_fails_closed_on_unimportable_modules() -> None:
    _GhostModuleSettings.__module__ = "no_such_module_for_coverage"
    assert _trusted_settings_fields(_GhostModuleSettings) is None


def test_annotation_kinds_accept_annotated_optional_forms() -> None:
    from typing import Annotated

    assert _secret_annotation_kind(Annotated[SecretStr, "meta"] | None) == (
        SecretStr,
        True,
    )
    assert _scalar_annotation_kind(Annotated[int, "meta"] | None) == (int, True)


def test_bundled_environment_scalar_normalization_guards() -> None:
    from scrapy_extension.settings._redacted import (
        _normalize_bundled_environment_scalar,
    )

    assert (
        _normalize_bundled_environment_scalar(RedisSettings, "db", int | None, None)
        is None
    )
    with pytest.raises(ConfigurationError, match="invalid value"):
        _normalize_bundled_environment_scalar(RedisSettings, "db", int | None, 12345)


def test_redacted_validation_error_covers_empty_error_lists() -> None:
    empty = ValidationError.from_exception_data("test", [])
    rebuilt = _redacted_validation_error(empty, frozenset({"port"}))
    assert [detail["loc"] for detail in rebuilt.errors()] == [("configuration",)]


def test_sanitize_backend_error_preserves_benign_plugin_subclasses() -> None:
    class _PluginError(BackendError):
        pass

    preserved = sanitize_backend_error(_PluginError("x"), message="replaced")
    assert type(preserved) is _PluginError
    assert preserved.args == ("replaced",)

    class _ForeignNew(BackendError):
        def __new__(cls, *args: Any) -> Any:
            return ValueError("not a backend error")

    foreign = BackendError.__new__(_ForeignNew)  # bypass the hostile __new__
    collapsed = sanitize_backend_error(foreign, message="replaced")
    assert type(collapsed) is BackendError


def test_set_operation_boundary_preserves_approved_static_messages() -> None:
    @set_operation_error_boundary(
        "set failed", "redis", safe_messages={"known static message"}
    )
    def operate() -> None:
        raise SetOutcomeIndeterminateError("known static message")

    with pytest.raises(SetOutcomeIndeterminateError, match="known static message"):
        operate()


def test_redact_message_masks_single_character_and_header_needles() -> None:
    # A one-character secret keeps surrounding words intact.
    assert _redact_message("bind q now", "q", force_setting_value=True) == (
        "bind ***REDACTED*** now"
    )
    # Sensitive header names embedded in a message are masked even when the
    # value was never passed through ``setting_value``.
    assert _redact_message("server said Authorization: abc123") == (
        "server said Authorization=***REDACTED***"
    )


def test_redact_setting_value_keeps_safe_mapping_keys() -> None:
    assert _redact_setting_value({"ordinary": "text"}, None) == {"ordinary": "text"}
