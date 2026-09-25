"""Base backend definitions and abstract interfaces.

This module defines the abstract base classes and interfaces that all
backend implementations must follow.
"""

from __future__ import annotations

__all__ = [
    "Backend",
    "BackendType",
    "JSONSerializer",
    "QueueBackend",
    "Serializer",
    "SetBackend",
    "StorageBackend",
]

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

# P3-1: BackendType lives in the dependency-free core.types leaf and is
# re-exported here (an __all__ member) for the existing backends.base
# importers; the key-name grammar moved with it — consumers import
# validate_key_name from the leaf directly.
from scrapy_extension.backends._json_codec import (  # noqa: F401 - P3-2 seam re-export
    JSONSerializer,
    Serializer,
    secret_value,
)
from scrapy_extension.core.types import BackendType
from scrapy_extension.exceptions.base import VALIDATION_VALUE_FRAGMENTS

# key-derived physical name (mirrors TOPIC_NAME_PATTERN in kafka.py).
_SENSITIVE_DIAGNOSTIC_FRAGMENTS = VALIDATION_VALUE_FRAGMENTS


def _safe_diagnostic_value(value: object) -> str:
    """Render validation values without echoing URI/credential-shaped text."""
    if type(value) is not str:
        return "<redacted>"
    lowered = value.lower()
    if "://" in value or any(
        fragment in lowered for fragment in _SENSITIVE_DIAGNOSTIC_FRAGMENTS
    ):
        return "<redacted>"
    return repr(value)


def _validate_ttl(ttl: int | None) -> None:
    """Validate the shared StorageBackend TTL input contract.

    ``None`` is the permanent-value sentinel. Concrete TTLs are positive
    integers; zero, negatives, floats, and bools otherwise diverge across
    Redis, MongoDB, ElasticSearch, DynamoDB, and Memcached.
    """
    if ttl is None:
        return
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
        raise ValueError("ttl must be a positive integer or None")


def _hash_item(item: bytes) -> str:
    """Generate SHA256 hash for item.

    Args:
        item: Item to hash.

    Returns:
        SHA256 hex digest.
    """
    return hashlib.sha256(item).hexdigest()


def _get_mode_text(mode: object) -> str:
    """Get a displayable string for a mode enum value.

    Args:
        mode: The mode enum value.

    Returns:
        A string representation of the mode.
    """
    try:
        return str(mode)
    except (TypeError, ValueError):
        return "<invalid-mode>"


class Backend(ABC):
    """Abstract base class for all backends.

    All backend implementations must inherit from this class and
    implement the abstract methods for connection management.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the backend.

        This method should create any necessary connections and
        prepare the backend for use.

        Raises:
            ConnectionError: If the connection cannot be established.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to the backend.

        This method should cleanly close all connections and
        release any resources.
        """

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the backend is connected.

        Returns:
            True if connected, False otherwise.
        """

    @abstractmethod
    def ping(self) -> bool:
        """Check backend health.

        Returns:
            True if the backend is healthy and responsive.
        """

    @property
    @abstractmethod
    def backend_type(self) -> BackendType | str:
        """Return the backend type.

        Round-5 R5-1: widened to ``BackendType | str`` so 3rd-party backends
        (registered via entry-points) can return a plain registry-key string
        instead of a bundled ``BackendType`` member. Bundled backends still
        return their canonical ``BackendType`` member — additive, no behavior
        change for the 10 bundled backends.

        Returns:
            The BackendType enum value (bundled) or registry-key string
            (3rd-party) for this backend.
        """


@dataclass(frozen=True, slots=True)
class _QueuePushReceipt:
    """Internal proof returned by the exact backend push operation.

    ``worker_crash_durable`` means the accepted item survives loss of the
    current crawler process.  It deliberately says nothing about a storage
    cluster or broker losing its own durable state.
    """

    worker_crash_durable: bool


class _DurablePushRequired(Exception):
    """Internal policy rejection that must not count as a backend failure."""


class QueueBackend(ABC):
    """Interface for queue operations.

    Backends that support queue operations must implement this interface.

    Ack-capability contract (round-2):

    - ``requires_ack``: True when ``pop`` yields a message that the caller
      MUST subsequently acknowledge via :meth:`ack` (else the message is
      redelivered). False for atomic-pop backends (Redis, MongoDB,
      ElasticSearch) — their pop removes the item in one step, so ack/nack
      are no-ops and the scheduler's ack wiring is inert. RocketMQ is
      deferred-ack (``requires_ack=True``): its gRPC ``receive`` yields a
      message the caller must ``ack`` before the invisible-duration window
      elapses (at-least-once redelivery), so it overrides ``pop_with_ack``
      / ``ack`` rather than inheriting the atomic defaults.
    - ``supports_concurrent_ack``: True when ack is safe under
      ``CONCURRENT_REQUESTS > 1`` (i.e. the backend tracks per-message ack
      state). **As of 2026-07-10 every bundled backend sets this True** —
      atomic-pop backends (Redis/MongoDB/ES) because ack is a no-op, and all
      five MQ backends (Kafka/RabbitMQ/RocketMQ/SQS/Pulsar) because each
      tracks a per-message token (in-flight set / ReceiptHandle / MessageId).
      A 3rd-party backend that can only hold a single ack slot may set False;
      the scheduler's ``from_settings`` gate then raises
      ``ConfigurationError`` for ``requires_ack and not
      supports_concurrent_ack`` under ``CONCURRENT_REQUESTS > 1`` unless the
      explicit ``SCRAPY_ACK_UNSAFE_CONCURRENT_REQUESTS`` opt-out is set. (The
      gate is unreachable for the 10 bundled backends — it remains a defensive
      backstop for a hypothetical single-slot 3rd-party backend.)

    Defaults are conservative for third-party implementations:
    ``requires_ack=False`` preserves legacy atomic-pop compatibility, while
    ``supports_concurrent_ack=False`` grants no concurrency claim unless a
    backend declares and implements the deferred-ack contract explicitly.
    """

    requires_ack: bool = False
    """True if pop yields a message needing explicit :meth:`ack` (MQ backends)."""

    supports_concurrent_ack: bool = False
    """True only when explicitly declared safe for overlapping deliveries."""

    _push_is_durable: ClassVar[bool] = False
    """Whether this backend invariably crosses a worker-crash durable boundary."""

    def _push_with_durability(
        self,
        queue_name: str,
        item: bytes,
        priority: float = 0.0,
        *,
        require_durable: bool = False,
    ) -> _QueuePushReceipt:
        """Push once and return operation-bound worker-crash durability.

        This concrete, package-private extension keeps pre-existing third-party
        ``QueueBackend`` implementations source compatible.  Their inherited
        default is fail-closed: ordinary pushes still delegate to the stable
        public :meth:`push`, while a durable-required transfer is rejected before
        the backend can mutate any process-local queue.
        """
        durable = self._push_is_durable is True
        if require_durable and not durable:
            raise _DurablePushRequired
        self.push(queue_name, item, priority)
        return _QueuePushReceipt(worker_crash_durable=durable)

    @abstractmethod
    def push(self, queue_name: str, item: bytes, priority: float = 0.0) -> None:
        """Push an item to a queue.

        Args:
            queue_name: The name of the queue.
            item: The item to push (serialized bytes).
            priority: Priority of the item (higher = more urgent).

        Raises:
            QueueError: If the push operation fails.
        """

    @abstractmethod
    def pop(self, queue_name: str, timeout: float = 0.0) -> bytes | None:
        """Pop an item from a queue.

        Args:
            queue_name: The name of the queue.
            timeout: Seconds to wait for an item (0 = non-blocking). Must be a
                finite, non-negative number. Atomic backends may ignore a
                positive wait; they still reject a malformed timeout.

        Returns:
            The popped item, or None if the queue is empty.

        Raises:
            QueueError: If the pop operation fails.
            ValueError: If ``timeout`` is not a finite, non-negative number.
        """

    @abstractmethod
    def queue_len(self, queue_name: str) -> int:
        """Get the number of items in a queue.

        Args:
            queue_name: The name of the queue.

        Returns:
            The number of items in the queue.
        """

    @abstractmethod
    def clear_queue(self, queue_name: str) -> None:
        """Clear all items from a queue.

        Args:
            queue_name: The name of the queue.
        """

    def pop_with_ack(
        self, queue_name: str, timeout: float = 0.0
    ) -> tuple[bytes | None, Any | None]:
        """Pop an item together with an opaque ack token.

        For atomic-pop backends (Redis, MongoDB, ElasticSearch) the default
        implementation returns ``(self.pop(queue_name, timeout), None)`` — there
        is no separate ack step, so the token is ``None``.

        Message-queue backends (Kafka, RabbitMQ) override to return a
        backend-specific token that the scheduler carries in
        ``request.meta["_backend_ack_token"]`` and hands back to
        :meth:`ack` / :meth:`nack` so the *specific* message that was popped
        is acked — not merely the last-popped one. This is what makes ack
        correct under ``CONCURRENT_REQUESTS > 1`` (N pops before any ack no
        longer overwrite a single slot).

        Args:
            queue_name: The name of the queue.
            timeout: Seconds to wait for an item (0 = non-blocking).

        Returns:
            A ``(item, token)`` tuple. ``item`` is ``None`` when the queue is
            empty; ``token`` is backend-specific (``None`` for atomic-pop
            backends, opaque to callers).

        Raises:
            QueueError: If the pop operation fails.
        """
        return (self.pop(queue_name, timeout), None)

    def ack(self, queue_name: str, *, token: Any | None = None) -> None:
        """Acknowledge a popped message for ``queue_name``.

        Atomic backends (Redis, MongoDB, ElasticSearch) implement this as a
        no-op: their pop is already atomic, so there is no "unacked" state to
        transition. Deferred-ack backends (Kafka, RabbitMQ, RocketMQ, Pulsar,
        SQS) override to commit the offset / basic_ack / consumer-ack the
        delivery.

        When ``token`` is provided (the scheduler always provides it for
        message-queue backends), the override acks the *specific* message
        identified by that token — correct under ``CONCURRENT_REQUESTS > 1``.
        When ``token`` is ``None`` (atomic backends, or legacy single-pop
        callers), overrides fall back to acking the last-popped message.

        The default no-op makes ack() safe to call from the scheduler even
        when the backend doesn't need it.

        Args:
            queue_name: The name of the queue whose message should be
                acknowledged.
            token: Opaque ack token returned by :meth:`pop_with_ack`. When
                ``None``, overrides ack the last-popped message (legacy).
        """
        del queue_name, token

    def nack(self, queue_name: str, *, token: Any | None = None) -> None:
        """Negatively acknowledge a popped message for ``queue_name``.

        Atomic backends implement this as a no-op. Message-queue backends
        override to requeue / re-deliver the message for another consumer.

        Args:
            queue_name: The name of the queue whose message should be
                negatively acknowledged.
            token: Opaque ack token returned by :meth:`pop_with_ack`. When
                ``None``, overrides nack the last-popped message (legacy).
        """
        del queue_name, token


class SetBackend(ABC):
    """Interface for set operations.

    Backends that support set operations must implement this interface.
    """

    @abstractmethod
    def add(self, set_name: str, item: bytes) -> bool:
        """Add an item to a set.

        Args:
            set_name: The name of the set.
            item: The item to add (serialized bytes).

        Returns:
            True if the item was added, False if it already existed.
        """

    @abstractmethod
    def remove(self, set_name: str, item: bytes) -> bool:
        """Remove an item from a set.

        Args:
            set_name: The name of the set.
            item: The item to remove.

        Returns:
            True if the item was removed, False if it didn't exist.
        """

    @abstractmethod
    def contains(self, set_name: str, item: bytes) -> bool:
        """Check if an item is in a set.

        Args:
            set_name: The name of the set.
            item: The item to check.

        Returns:
            True if the item exists in the set.
        """

    @abstractmethod
    def set_len(self, set_name: str) -> int:
        """Get the number of items in a set.

        Args:
            set_name: The name of the set.

        Returns:
            The number of items in the set.
        """

    @abstractmethod
    def clear_set(self, set_name: str) -> None:
        """Clear all items from a set.

        Args:
            set_name: The name of the set.
        """


class StorageBackend(ABC):
    """Interface for storage operations.

    Backends that support storage operations must implement this interface.
    """

    @abstractmethod
    def store(self, key: str, data: bytes, ttl: int | None = None) -> None:
        """Store data with a key.

        Args:
            key: The storage key.
            data: The data to store (bytes).
            ttl: Optional time-to-live in seconds.
        """

    @abstractmethod
    def retrieve(self, key: str) -> bytes | None:
        """Retrieve data by key.

        Args:
            key: The storage key.

        Returns:
            The stored data, or None if not found.
        """

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete data by key.

        Args:
            key: The storage key.

        Returns:
            True if the key was deleted, False if it didn't exist.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists.

        Args:
            key: The storage key.

        Returns:
            True if the key exists.
        """

    @abstractmethod
    def ttl(self, key: str) -> int | None:
        """Get the remaining time-to-live for a key.

        Args:
            key: The storage key.

        Returns:
            Non-negative seconds remaining, or None when the key is missing,
            has no TTL, or has already expired. A backend that cannot inspect
            remaining TTL (for example Memcached) may also return None for a live
            expiring key; callers must treat None as "no observable live TTL".
        """

    def list_storage_keys(self, prefix: str = "", *, limit: int = 1_000) -> list[str]:
        """List a bounded, explicitly scoped set of logical storage keys.

        This optional maintenance capability is deliberately separate from
        ``clear_storage``. Backends that cannot safely enumerate their owned
        namespace may retain the default ``NotImplementedError``; callers must
        never emulate listing by clearing or guessing physical keys.
        """
        del prefix, limit
        raise NotImplementedError

    @abstractmethod
    def clear_storage(self, prefix: str | None = None) -> None:
        """Clear all stored data, optionally filtered by prefix.

        Args:
            prefix: If provided, only clear keys starting with this prefix. If None,
                clear all storage data.
        """
