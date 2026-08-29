from scrapy_extension.exceptions._redaction import (
    backend_connection_error_boundary,
    configuration_error_boundary,
    control_exception_traceback_boundary,
    import_error_traceback_boundary,
    not_implemented_error_boundary,
    queue_operation_error_boundary,
    sanitize_backend_error,
    sanitize_configuration_error,
    serialization_error_boundary,
    set_operation_error_boundary,
    storage_operation_error_boundary,
)
from scrapy_extension.exceptions.base import (
    BackendConnectionError,
    BackendError,
    BackendOperationTimeout,
    ConfigurationError,
    QueueError,
    QueueOutcomeIndeterminateError,
    SerializationError,
    SetOutcomeIndeterminateError,
    StorageBackpressureError,
    StorageError,
    StorageOutcomeIndeterminateError,
)

# P3-6: the package init is the public seam for the error-boundary
# decorators and the sanitizer — consumers no longer reach into the private
# _redaction module path.
__all__ = [
    "BackendConnectionError",
    "BackendError",
    "BackendOperationTimeout",
    "ConfigurationError",
    "QueueError",
    "QueueOutcomeIndeterminateError",
    "SerializationError",
    "SetOutcomeIndeterminateError",
    "StorageBackpressureError",
    "StorageError",
    "StorageOutcomeIndeterminateError",
    "backend_connection_error_boundary",
    "configuration_error_boundary",
    "control_exception_traceback_boundary",
    "import_error_traceback_boundary",
    "not_implemented_error_boundary",
    "queue_operation_error_boundary",
    "sanitize_backend_error",
    "sanitize_configuration_error",
    "serialization_error_boundary",
    "set_operation_error_boundary",
    "storage_operation_error_boundary",
]
