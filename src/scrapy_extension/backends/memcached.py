"""Memcached backend (StorageBackend) — distributed KV cache (subsystem ③).

Implements StorageBackend using Memcached (key-value, TTL via ``expire``).
Does NOT implement QueueBackend or SetBackend — Memcached has no native
ordered queue or set data structure. Adds a NoSQL key-value backend
complementary to the existing Redis/MongoDB/ES storage backends.

pymemcache API used (stable):
- ``pymemcache.client.base.Client((host, port))``
- ``client.set(key, value, expire=ttl)``
- ``client.get(key)``
- ``client.delete(key)``
- ``client.flush_all()``
- ``client.stats()``
- ``client.close()``
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from threading import Condition, Lock
from typing import Any, ParamSpec, TypeVar

from scrapy_extension.backends._optional import _is_missing_optional_dependency
from scrapy_extension.core.types import validate_key_name as _validate_key_name

try:
    from pymemcache.client.base import Client as MemcachedClient
except ImportError as e:
    if not _is_missing_optional_dependency(e, "pymemcache"):
        raise
    raise ImportError(
        "Memcached backend requires 'pymemcache'. "
        "Install with: pip install scrapy-extension[memcached]"
    ) from e

from scrapy_extension.backends._close import close_handles, swallow_close_failures
from scrapy_extension.backends.base import (
    Backend,
    BackendType,
    StorageBackend,
    _validate_ttl,
)
from scrapy_extension.exceptions import (
    BackendConnectionError,
    backend_connection_error_boundary,
    configuration_error_boundary,
    storage_operation_error_boundary,
)
from scrapy_extension.exceptions.base import StorageError
from scrapy_extension.settings import MemcachedMode, MemcachedSettings
from scrapy_extension.settings.memcached import (
    is_memcached_loopback,
    validate_memcached_connection,
    validate_memcached_flush_policy,
    validate_memcached_timeout,
)

logger = logging.getLogger(__name__)

_P = ParamSpec("_P")
_T = TypeVar("_T")

_MEMCACHED_CONFIGURATION_SETTING_NAMES: frozenset[str] = frozenset(
    MemcachedSettings.model_fields
)
_MEMCACHED_SAFE_CONNECTION_MESSAGES: frozenset[str] = frozenset(
    {"Failed to connect to Memcached."}
)
_MEMCACHED_STORAGE_STORE_ERROR = "Memcached storage store failed."
_MEMCACHED_STORAGE_RETRIEVE_ERROR = "Memcached storage retrieve failed."
_MEMCACHED_STORAGE_DELETE_ERROR = "Memcached storage delete failed."
_MEMCACHED_STORAGE_EXISTS_ERROR = "Memcached storage existence check failed."
_MEMCACHED_STORAGE_CLEAR_ERROR = "Memcached storage clear failed."
# Memcached reads an exptime > 30 days (2_592_000s) as an ABSOLUTE Unix epoch
# timestamp, not relative seconds. Relative TTLs above this bound must be
# converted to (now + ttl) so the server does not treat them as a past
# timestamp and silently expire the item on write.
_MEMCACHED_MAX_RELATIVE_TTL_SECONDS = 60 * 60 * 24 * 30  # 2_592_000
_MEMCACHED_CLEAR_STORAGE_PREFIX_UNSUPPORTED_MESSAGE = (
    "Memcached flush_all does not support prefix scoping; pass "
    "prefix=None only when a server-wide flush is explicitly acceptable."
)
_MEMCACHED_CLEAR_STORAGE_DISABLED_MESSAGE = (
    "Memcached clear_storage would flush every key on the server. Set "
    "SCRAPY_MEMCACHED_ALLOW_FLUSH_ALL=true (allow_flush_all=True) only "
    "for a dedicated cache where that destructive scope is intended."
)
_MEMCACHED_CLEAR_STORAGE_CAPABILITY_MESSAGES: frozenset[str] = frozenset(
    {
        _MEMCACHED_CLEAR_STORAGE_PREFIX_UNSUPPORTED_MESSAGE,
        _MEMCACHED_CLEAR_STORAGE_DISABLED_MESSAGE,
    }
)


def _memcached_connect_reentry_boundary(
    function: Callable[..., Any],
) -> Callable[..., Any]:
    """Reject callbacks that would recursively take the connect lock."""

    @wraps(function)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        depth = int(getattr(self._connect_local, "depth", 0))
        if depth:
            raise BackendConnectionError(
                "Cannot connect to Memcached re-entrantly during connect.",
                backend_type="memcached",
            )
        self._connect_local.depth = depth + 1
        try:
            return function(self, *args, **kwargs)
        finally:
            self._connect_local.depth = depth

    return wrapped


def _validate_stats_response(response: object) -> Mapping[object, object]:
    """Require the mapping contract published by ``pymemcache.stats``."""
    if not isinstance(response, Mapping):
        raise TypeError("Memcached stats returned a malformed response.")
    return response


def _validate_get_response(response: object) -> bytes | None:
    """Normalize the documented byte-oriented ``pymemcache.get`` response."""
    if response is None:
        return None
    if isinstance(response, bytes):
        return response
    if isinstance(response, bytearray):
        return bytes(response)
    raise TypeError("Memcached get returned a malformed response.")


def _validate_delete_response(response: object) -> bool:
    """Require an exact acknowledgement boolean from ``pymemcache.delete``."""
    if type(response) is not bool:
        raise TypeError("Memcached delete returned a malformed response.")
    return response


# Memcached rejects keys longer than 250 bytes server-side; fail fast on the
# logical name instead of surfacing a driver error after the write is lost.
_MEMCACHED_MAX_KEY_LENGTH_BYTES = 250


def _validate_memcached_key(name: str, field_name: str = "key") -> None:
    """Validate a logical key against the Memcached server-side byte limit."""
    _validate_key_name(name, field_name, max_length=_MEMCACHED_MAX_KEY_LENGTH_BYTES)


def _validate_storage_key_argument(
    _backend: object,
    key: str,
    *_args: Any,
    **_kwargs: Any,
) -> None:
    """Validate a direct Memcached storage key before implementation frames."""
    _validate_memcached_key(key, "key")


def _validate_store_arguments(
    _backend: object,
    key: str,
    data: bytes,
    ttl: int | None = None,
) -> None:
    """Validate a direct Memcached storage write before its terminal boundary."""
    del data
    _validate_memcached_key(key, "key")
    _validate_ttl(ttl)


def _validate_storage_prefix_argument(
    _backend: object,
    prefix: str | None = None,
) -> None:
    """Validate a non-empty clear prefix before backend implementation frames."""
    if prefix is not None:
        _validate_memcached_key(prefix, "prefix")


def _clear_storage_capability_error_boundary(
    function: Callable[_P, _T],
) -> Callable[_P, _T]:
    """Rebuild the two documented Memcached clear capability errors safely.

    ``clear_storage`` intentionally has two distinct static
    :class:`NotImplementedError` contracts: prefix-scoped flushing is not
    possible and a server-wide flush needs an explicit connected-generation
    opt-in.  Both literals are public API, but raising either from the backend
    method retains its configuration and caller prefix in traceback locals.
    Reconstruct only those exact built-in errors after all implementation frames
    unwind; subclasses and unknown behavior keep their established contract.
    """

    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        caught_error: NotImplementedError | None = None
        try:
            return function(*args, **kwargs)
        except NotImplementedError as error:
            if type(error) is not NotImplementedError:
                del args
                del kwargs
                raise
            caught_error = error
        except BaseException:
            del args
            del kwargs
            raise

        assert caught_error is not None
        replacement_message = _MEMCACHED_CLEAR_STORAGE_DISABLED_MESSAGE
        raw_args: object = caught_error.args
        if (
            type(raw_args) is tuple
            and len(raw_args) == 1
            and type(raw_args[0]) is str
            and raw_args[0] in _MEMCACHED_CLEAR_STORAGE_CAPABILITY_MESSAGES
        ):
            replacement_message = raw_args[0]
        sanitized_error = NotImplementedError(replacement_message)
        del args
        del kwargs
        del caught_error
        del raw_args
        del replacement_message
        raise sanitized_error

    return wrapped


@dataclass(frozen=True)
class _MemcachedConnectionSnapshot:
    """One validated set of values used by a Memcached connect attempt."""

    mode: MemcachedMode
    host: str
    port: int
    allow_remote_plaintext: bool
    connect_timeout: float
    socket_timeout: float
    allow_flush_all: bool


class MemcachedBackend(Backend, StorageBackend):
    """Memcached storage backend (KV with TTL).

    Stores values under keys with an optional TTL (``expire``). Limitations
    (Memcached has no native support): ``ttl()`` always returns ``None``
    (remaining TTL not exposed). Memcached cannot enumerate or prefix-filter
    keys, so ``clear_storage`` is disabled by default; the destructive
    server-wide ``flush_all`` operation requires ``allow_flush_all=True``.

    Attributes:
        config: MemcachedSettings instance.
        _client: The validated connect-probe pymemcache Client (None until
            connected). Each operating thread owns a separate client built
            from the same validated snapshot; the probe is the connecting
            thread's client.
    """

    def __init__(self, config: MemcachedSettings) -> None:
        """Initialize the Memcached backend.

        Args:
            config: Configuration for the Memcached connection.
        """
        self.config = config
        self._client: Any = None
        self._connection_snapshot: _MemcachedConnectionSnapshot | None = None
        # pymemcache's ordinary Client owns one request/response socket and is not
        # thread-safe, so a socket must never be shared across threads. Instead of
        # one process-global lock serializing every transaction on one shared
        # client, each operating thread gets its own client built lazily from the
        # validated connection snapshot (pymemcache opens no socket until the
        # first command, so construction performs no I/O under the lifecycle
        # lock). Transactions no longer serialize against each other; only
        # teardown waits: disconnect drains the in-flight count, then closes
        # every distinct client exactly once.
        self._connect_lock = Lock()
        self._disconnect_lock = Lock()
        self._connect_local = threading.local()
        self._operation_local = threading.local()
        self._disconnecting = False
        self._disconnect_owner: int | None = None
        self._lifecycle_lock = Lock()
        # Notified under _lifecycle_lock when an operation leaves its socket.
        self._operation_condition = Condition(self._lifecycle_lock)
        self._lifecycle_generation = 0
        # thread ident -> that thread's client for the live generation; a
        # finished thread keeps its client until disconnect (bounded by the
        # crawl's thread count, not by operations).
        self._thread_clients: dict[int, Any] = {}
        self._operations_in_flight = 0

    @configuration_error_boundary(
        "Memcached configuration is invalid.",
        _MEMCACHED_CONFIGURATION_SETTING_NAMES,
    )
    def _capture_connection_snapshot(self) -> _MemcachedConnectionSnapshot:
        """Capture and revalidate every value used by one connect attempt."""
        mode, host, port, allow_remote = validate_memcached_connection(
            self.config.mode,
            self.config.host,
            self.config.port,
            self.config.allow_remote_plaintext,
        )
        connect_timeout = validate_memcached_timeout(
            self.config.connect_timeout, "connect_timeout"
        )
        socket_timeout = validate_memcached_timeout(
            self.config.socket_timeout, "socket_timeout"
        )
        allow_flush_all = validate_memcached_flush_policy(self.config.allow_flush_all)
        return _MemcachedConnectionSnapshot(
            mode=mode,
            host=host,
            port=port,
            allow_remote_plaintext=allow_remote,
            connect_timeout=connect_timeout,
            socket_timeout=socket_timeout,
            allow_flush_all=allow_flush_all,
        )

    @backend_connection_error_boundary(
        "Failed to connect to Memcached.",
        "memcached",
        safe_messages=_MEMCACHED_SAFE_CONNECTION_MESSAGES,
    )
    @configuration_error_boundary(
        "Memcached configuration is invalid.",
        _MEMCACHED_CONFIGURATION_SETTING_NAMES,
        pass_through_exception_types=(BackendConnectionError,),
    )
    @_memcached_connect_reentry_boundary
    def connect(self) -> None:
        """Connect to Memcached and verify with a stats() call.

        The candidate remains private until ``stats()`` succeeds. On failure it is
        closed without ever publishing ``_client``, so :meth:`is_connected`
        truthfully remains false. Repeated calls while connected are idempotent.

        Raises:
            BackendConnectionError: If the connection cannot be established.
        """
        with self._connect_lock:
            with self._lifecycle_lock:
                if self._disconnecting:
                    raise BackendConnectionError(
                        "Cannot connect to Memcached while disconnecting.",
                        backend_type="memcached",
                    )
                if self._client is not None:
                    return
                generation = self._lifecycle_generation
            snapshot = self._capture_connection_snapshot()
            candidate: Any = None
            startup_error: BackendConnectionError | None = None
            try:
                # pymemcache defaults ``default_noreply=True``. In that mode set,
                # delete, and flush can return success after only writing the command
                # to the socket; the server's STORED/DELETED/error response is never
                # read. StorageBackend success is a commit boundary, so require replies
                # for every mutating operation on this client generation.
                candidate = MemcachedClient(
                    (snapshot.host, snapshot.port),
                    connect_timeout=snapshot.connect_timeout,
                    timeout=snapshot.socket_timeout,
                    default_noreply=False,
                )
                _validate_stats_response(candidate.stats())
            except Exception:
                if candidate is not None:
                    _close_failed_candidate(candidate)
                startup_error = BackendConnectionError(
                    "Failed to connect to Memcached.", backend_type="memcached"
                )
            except BaseException:
                # R17-C: a Ctrl+C/SystemExit during the stats() probe (the first command
                # to open the TCP socket — pymemcache is lazy) must still close the
                # candidate socket. 'except Exception' cannot catch BaseException, so
                # without this arm a KeyboardInterrupt raised by stats() escapes before
                # candidate.close() runs, leaking the open FD. Candidate is never
                # published (generation-fenced at the publish step below), so
                # is_connected() stays truthful — bounded to a single FD per occurrence.
                # Mirror the R16-A kafka/rocketmq/dynamodb connect() BaseException arms.
                if candidate is not None:
                    _close_failed_candidate(candidate)
                raise
            if startup_error is not None:
                # Raise outside the driver exception handler so endpoint/credential
                # text cannot survive through ``__cause__`` or ``__context__``.
                raise startup_error
            published = False
            try:
                with self._lifecycle_lock:
                    # A concurrent disconnect fences this private probe by advancing the
                    # lifecycle generation. Never resurrect a client after teardown.
                    publish = (
                        generation == self._lifecycle_generation
                        and not self._disconnecting
                    )
                    if publish:
                        # Install the snapshot first; assigning _client last is
                        # the mirror's ownership commit point.  An interruption
                        # before that assignment leaves no live client to leak.
                        self._connection_snapshot = snapshot
                        self._client = candidate
                        # The probe client belongs to this thread's socket; later
                        # operations on this thread reuse it instead of paying
                        # for a duplicate construction.
                        self._thread_clients[threading.get_ident()] = candidate
                        published = True
            except BaseException:
                # Publication is the ownership transfer.  If control flow is
                # interrupted before that transfer, the private socket still belongs
                # to this failed connect attempt and must be closed.  Conversely, a
                # published candidate is live and must not be rolled back here.
                if not published:
                    _close_failed_candidate(candidate)
                raise
            if not publish:
                cleanup = _swallow()
                with cleanup:
                    candidate.close()
                if cleanup.did_suppress:
                    _log_suppressed_cleanup_error()
                return
            if not is_memcached_loopback(snapshot.host):
                # The client is already live. Diagnostics must not make a successful
                # connect appear to fail or cause callers to roll back this generation.
                try:
                    logger.warning(
                        "Remote Memcached plaintext was explicitly enabled; use only an "
                        "isolated trusted network."
                    )
                except BaseException:
                    pass
            try:
                logger.debug("Connected to Memcached.")
            except BaseException:
                pass

    @contextmanager
    def _operation(self, operation: str) -> Iterator[Any]:
        """Bind this thread's client and account the transaction for teardown."""
        previous_depth = int(getattr(self._operation_local, "depth", 0))
        if previous_depth:
            raise BackendConnectionError(
                f"Cannot run Memcached {operation} re-entrantly.",
                backend_type="memcached",
            )
        with self._lifecycle_lock:
            if self._disconnecting:
                raise BackendConnectionError(
                    f"Cannot run Memcached {operation} while disconnecting.",
                    backend_type="memcached",
                )
            client = self._thread_client_locked()
            self._operations_in_flight += 1
        self._operation_local.depth = previous_depth + 1
        try:
            yield client
        finally:
            self._operation_local.depth = previous_depth
            with self._lifecycle_lock:
                self._operations_in_flight -= 1
                self._operation_condition.notify_all()

    def _thread_client_locked(self) -> Any:
        """Return this thread's client for the live generation.

        The caller holds ``_lifecycle_lock``. Registration happens before the
        first command, and pymemcache opens no socket until that first command,
        so constructing a client here performs no I/O while the lock is held
        (``default_noreply=False`` for the same commit-boundary reason as the
        connect probe -- see :meth:`connect`).
        """
        snapshot = self._connection_snapshot
        if snapshot is None:
            # Never connected or already disconnected: preserve the legacy
            # None-client path so operations surface the same StorageError.
            return None
        ident = threading.get_ident()
        client = self._thread_clients.get(ident)
        if client is None:
            client = MemcachedClient(
                (snapshot.host, snapshot.port),
                connect_timeout=snapshot.connect_timeout,
                timeout=snapshot.socket_timeout,
                default_noreply=False,
            )
            self._thread_clients[ident] = client
        return client

    @contextmanager
    def _disconnect_barrier(self) -> Iterator[bool]:
        """Own teardown and make close callbacks idempotent instead of recursive."""
        current_thread = threading.get_ident()
        with self._lifecycle_lock:
            if self._disconnect_owner == current_thread:
                yield False
                return
            if int(getattr(self._operation_local, "depth", 0)):
                raise BackendConnectionError(
                    "Cannot disconnect Memcached re-entrantly from an active operation.",
                    backend_type="memcached",
                )
        with self._disconnect_lock:
            with self._lifecycle_lock:
                if self._disconnect_owner == current_thread:
                    yield False
                    return
                self._disconnect_owner = current_thread
                self._disconnecting = True
            try:
                yield True
            finally:
                with self._lifecycle_lock:
                    if self._disconnect_owner == current_thread:
                        self._disconnect_owner = None
                        self._disconnecting = False

    def disconnect(self) -> None:
        """Detach, drain, and close every Memcached client."""
        with self._disconnect_barrier() as owns_barrier:
            if not owns_barrier:
                return
            with self._lifecycle_lock:
                self._lifecycle_generation += 1
                # Snapshot every distinct live client once (the probe and the
                # per-thread registry usually alias the same instances).
                clients: list[Any] = []
                for client in (self._client, *self._thread_clients.values()):
                    if client is not None and client not in clients:
                        clients.append(client)
                self._client = None
                self._connection_snapshot = None
                self._thread_clients.clear()
                # Drain: each in-flight transaction holds its client reference;
                # wait for the last one to leave its socket before closing.
                # In-flight commands are bounded by socket_timeout, so this
                # wait inherits the same bound the lock handoff had.
                while self._operations_in_flight:
                    self._operation_condition.wait()
            # P2-5: one shared close outcome — ordinary close failures surface
            # one static diagnostic, and a control exception is re-raised only
            # after every distinct client has been attempted.
            failed, control_error = close_handles(*clients)
            if failed:
                _log_suppressed_cleanup_error()
            if control_error is not None:
                raise control_error

    def is_connected(self) -> bool:
        """Return True if the client has been created."""
        with self._lifecycle_lock:
            return self._client is not None

    def ping(self) -> bool:
        """Check Memcached health via stats().

        Returns:
            True if stats() succeeds.
        """
        with self._operation("ping") as client:
            if client is None:
                return False
            try:
                _validate_stats_response(client.stats())
                return True
            except Exception:
                return False

    @property
    def backend_type(self) -> BackendType:
        """Return BackendType.MEMCACHED."""
        return BackendType.MEMCACHED

    # StorageBackend implementation
    @storage_operation_error_boundary(
        "store",
        _MEMCACHED_STORAGE_STORE_ERROR,
        "memcached",
        validator=_validate_store_arguments,
    )
    def store(self, key: str, data: bytes, ttl: int | None = None) -> None:
        """Store ``data`` under ``key`` with optional TTL.

        Args:
            key: Storage key.
            data: Data to store (bytes).
            ttl: Optional time-to-live in seconds.

        Raises:
            ValueError: If key contains invalid characters.
            StorageError: If the underlying client raises (was previously
                silently swallowed to ``return None``, masking data loss).
        """
        _validate_memcached_key(key, "key")
        _validate_ttl(ttl)
        with self._operation("store") as client:
            try:
                if ttl is None:
                    expire = 0
                elif ttl > _MEMCACHED_MAX_RELATIVE_TTL_SECONDS:
                    # Memcached reads exptime > 30 days as an absolute Unix
                    # epoch; convert the relative TTL so the item is not
                    # silently expired as a past timestamp.
                    expire = int(time.time()) + ttl
                else:
                    expire = ttl
                stored = client.set(key, data, expire=expire)
            except Exception as e:
                msg = f"Failed to store key {key!r} in Memcached: {e}"
                raise StorageError(msg, operation="store", key=key) from e
        if stored is not True:
            raise StorageError(
                f"Memcached rejected the write for key {key!r}",
                operation="store",
                key=key,
            )

    @storage_operation_error_boundary(
        "retrieve",
        _MEMCACHED_STORAGE_RETRIEVE_ERROR,
        "memcached",
        validator=_validate_storage_key_argument,
    )
    def retrieve(self, key: str) -> bytes | None:
        """Retrieve data by key.

        Args:
            key: Storage key.

        Returns:
            Stored data, or None if not found.

        Raises:
            ValueError: If key contains invalid characters.
            StorageError: If the underlying client raises (was previously
                silently swallowed to ``return None``).
        """
        _validate_memcached_key(key, "key")
        with self._operation("retrieve") as client:
            try:
                return _validate_get_response(client.get(key))
            except Exception as e:
                msg = f"Failed to retrieve key {key!r} from Memcached: {e}"
                raise StorageError(msg, operation="retrieve", key=key) from e

    @storage_operation_error_boundary(
        "delete",
        _MEMCACHED_STORAGE_DELETE_ERROR,
        "memcached",
        validator=_validate_storage_key_argument,
    )
    def delete(self, key: str) -> bool:
        """Delete data by key.

        Args:
            key: Storage key.

        Returns:
            True if the key existed and was deleted, False otherwise.

        Raises:
            ValueError: If key contains invalid characters.
            StorageError: If the underlying client raises (was previously
                silently swallowed to ``return False``).
        """
        _validate_memcached_key(key, "key")
        with self._operation("delete") as client:
            try:
                return _validate_delete_response(client.delete(key))
            except Exception as e:
                msg = f"Failed to delete key {key!r} in Memcached: {e}"
                raise StorageError(msg, operation="delete", key=key) from e

    @storage_operation_error_boundary(
        "exists",
        _MEMCACHED_STORAGE_EXISTS_ERROR,
        "memcached",
        validator=_validate_storage_key_argument,
    )
    def exists(self, key: str) -> bool:
        """Check if a key exists.

        Args:
            key: Storage key.

        Returns:
            True if the key exists.

        Raises:
            ValueError: If key contains invalid characters.
            StorageError: If the underlying client raises (was previously
                silently swallowed to ``return False``).
        """
        _validate_memcached_key(key, "key")
        with self._operation("exists") as client:
            try:
                return _validate_get_response(client.get(key)) is not None
            except Exception as e:
                msg = f"Failed to check existence of key {key!r} in Memcached: {e}"
                raise StorageError(msg, operation="exists", key=key) from e

    def ttl(self, key: str) -> int | None:
        """Return None — Memcached does not expose remaining TTL.

        Args:
            key: Storage key.

        Returns:
            Always None (unsupported by Memcached).

        Raises:
            ValueError: If key contains invalid characters.
        """
        _validate_memcached_key(key, "key")
        return None

    @_clear_storage_capability_error_boundary
    @storage_operation_error_boundary(
        "clear_storage",
        _MEMCACHED_STORAGE_CLEAR_ERROR,
        "memcached",
        validator=_validate_storage_prefix_argument,
    )
    def clear_storage(self, prefix: str | None = None) -> None:
        """Flush all server keys only when explicitly enabled.

        Args:
            prefix: A non-None prefix is always rejected because Memcached cannot
                scope ``flush_all``. ``None`` is accepted only when the backend
                was configured with ``allow_flush_all=True``.

        Raises:
            ValueError: If ``prefix`` contains invalid characters.
            NotImplementedError: If prefix scoping is requested or the destructive
                global flush has not been explicitly enabled.
            StorageError: If the backend is not connected or the underlying
                client raises (was previously silently swallowed).
        """
        if prefix is not None:
            _validate_memcached_key(prefix, "prefix")
            raise NotImplementedError(
                _MEMCACHED_CLEAR_STORAGE_PREFIX_UNSUPPORTED_MESSAGE
            )
        with self._operation("clear_storage") as client:
            with self._lifecycle_lock:
                snapshot = self._connection_snapshot
            if snapshot is None:
                # Lifecycle state, not a capability gap (never-connected or
                # disconnected): advise reconnection, not the flush flag an
                # operator may already have enabled.
                raise StorageError(
                    "Memcached backend is not connected",
                    operation="clear_storage",
                    key=None,
                )
            if not snapshot.allow_flush_all:
                raise NotImplementedError(_MEMCACHED_CLEAR_STORAGE_DISABLED_MESSAGE)
            try:
                flushed = client.flush_all()
            except Exception as e:
                msg = f"Failed to flush Memcached: {e}"
                raise StorageError(msg, operation="clear_storage", key=None) from e
            if flushed is not True:
                raise StorageError(
                    "Memcached rejected the server-wide flush.",
                    operation="clear_storage",
                    key=None,
                )


_swallow = swallow_close_failures


def _log_suppressed_cleanup_error() -> None:
    """Report a suppressed cleanup failure after its exception context unwinds."""
    try:
        logger.debug("Suppressed memcached cleanup error")
    except BaseException:
        # A diagnostic handler must not turn best-effort teardown into a failure.
        pass


def _close_failed_candidate(candidate: Any) -> None:
    """Best-effort cleanup for a private connect candidate.

    The caller is already handling the causal probe exception.  Unlike
    ``_swallow``, this must not run diagnostics that can replace that exception;
    close-time control signals are therefore intentionally suppressed here.
    """
    try:
        candidate.close()
    except BaseException:
        pass
