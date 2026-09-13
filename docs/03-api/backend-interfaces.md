# Backend Interface Contracts

The four abstract base classes that every backend — bundled or third-party —
implements. They live in `scrapy_extension.backends.base` and are re-exported
from the package root. All four are **Stable** (tiering in
[STABILITY.md](../../.github/STABILITY.md)); the `_`-prefixed durability
receipt helpers are Internal.

For entry-point registration, the `BackendDescriptor` dataclass, and a worked
plugin example, see [Backend Plugins](../06-guides/developer-guides/backend-plugins.md).
This document is the interface contract those plugins must satisfy.

## Canonical imports and value invariants

Application code should import the interfaces from the package root:

```python
from scrapy_extension import Backend, QueueBackend, SetBackend, StorageBackend
```

The implementation module (`scrapy_extension.backends.base`) re-exports the
same names for backend authors and type-checking. Queue and set payloads are
already serialized `bytes`; these interfaces do not encode or decode values.
Names and storage keys are logical `str` values. Genuine misses use the
documented `None`/`False` sentinel; SDK or transport failures must raise the
typed backend error rather than returning a success sentinel.

## `Backend` — lifecycle

Every backend inherits `Backend` and implements all of:

| Member | Signature | Contract |
| ------ | --------- | -------- |
| `connect` | `() -> None` | Establish connections and prepare the backend; raise `ConnectionError` when the backend is unreachable. |
| `disconnect` | `() -> None` | Cleanly close all connections and release resources. |
| `is_connected` | `() -> bool` | `True` while connected. |
| `ping` | `() -> bool` | `True` when the backend is healthy and responsive. |
| `backend_type` | property `-> BackendType \| str` | Bundled backends return their `BackendType` member; third-party backends may return their registry-key string. |

## `QueueBackend` — queue operations

| Member | Signature | Contract |
| ------ | --------- | -------- |
| `push` *(abstract)* | `(queue_name: str, item: bytes, priority: float = 0.0) -> None` | Enqueue serialized bytes; higher priority = more urgent. Raises `QueueError` on failure. |
| `pop` *(abstract)* | `(queue_name: str, timeout: float = 0.0) -> bytes \| None` | Dequeue one item; `timeout` is seconds to wait, `0` = non-blocking. `None` when the queue is empty. Raises `QueueError` on failure. |
| `queue_len` *(abstract)* | `(queue_name: str) -> int` | Number of items in the queue. Pulsar and RocketMQ raise `NotImplementedError` instead of reporting a false zero depth. |
| `clear_queue` *(abstract)* | `(queue_name: str) -> None` | Remove all items from the queue. |
| `pop_with_ack` | `(queue_name: str, timeout: float = 0.0) -> tuple[bytes \| None, Any \| None]` | Pop plus an opaque ack token. Default returns `(self.pop(...), None)`. |
| `ack` | `(queue_name: str, *, token: Any \| None = None) -> None` | Acknowledge a popped message. Default is a no-op. |
| `nack` | `(queue_name: str, *, token: Any \| None = None) -> None` | Negatively acknowledge (requeue/re-deliver). Default is a no-op. |

Third-party implementations must provide only the four abstract methods; the
ack methods above are inherited concrete defaults.

### Ack capability contract

Two class attributes declare how a backend acknowledges deliveries:

| Attribute | Default | Meaning |
| --------- | ------- | ------- |
| `requires_ack` | `False` | `pop` yields a message the caller MUST `ack` (or it is redelivered). `False` for atomic-pop backends. |
| `supports_concurrent_ack` | `False` | Ack state is tracked per message, so overlapping deliveries are safe under `CONCURRENT_REQUESTS > 1`. Every bundled backend sets this `True`. |

Bundled backends split into two families:

- **Atomic-pop** — Redis, MongoDB, ElasticSearch. Pop removes the item in one
  step; `pop_with_ack()` returns `(item, None)` and `ack()` / `nack()` are no-ops.
- **Deferred-ack** — Kafka, RabbitMQ, RocketMQ, Pulsar, SQS. Pop yields a
  message that must be acked before its visibility/invisibility window elapses
  (at-least-once redelivery). Each backend tracks a per-message token that
  rides in `request.meta["_backend_ack_token"]` so `ack`/`nack` settle the
  *specific* message, not merely the last-popped one.

The scheduler raises `ConfigurationError` for a backend with
`requires_ack and not supports_concurrent_ack` under `CONCURRENT_REQUESTS > 1`,
unless `SCRAPY_ACK_UNSAFE_CONCURRENT_REQUESTS` opts out. No bundled backend can
hit this gate — it is a defensive backstop for third-party implementations.

## `SetBackend` — membership operations

| Member | Signature | Contract |
| ------ | --------- | -------- |
| `add` | `(set_name: str, item: bytes) -> bool` | `True` if added; `False` if already present. |
| `remove` | `(set_name: str, item: bytes) -> bool` | `True` if removed; `False` if absent. |
| `contains` | `(set_name: str, item: bytes) -> bool` | `True` if present. |
| `set_len` | `(set_name: str) -> int` | Number of items in the set. |
| `clear_set` | `(set_name: str) -> None` | Remove all items from the set. |

## `StorageBackend` — key/value operations

| Member | Signature | Contract |
| ------ | --------- | -------- |
| `store` | `(key: str, data: bytes, ttl: int \| None = None) -> None` | Store bytes under a key. |
| `retrieve` | `(key: str) -> bytes \| None` | Stored bytes, or `None` if not found. |
| `delete` | `(key: str) -> bool` | `True` if deleted; `False` if absent. |
| `exists` | `(key: str) -> bool` | `True` if the key exists. |
| `ttl` | `(key: str) -> int \| None` | Remaining time-to-live (see below). |
| `clear_storage` | `(prefix: str \| None = None) -> None` | Clear all data, optionally scoped to a prefix. |
| `list_storage_keys` | `(prefix: str = "", *, limit: int = 1_000) -> list[str]` | Optional maintenance capability; the default raises `NotImplementedError`. |

Storage failures raise `StorageError` — never a silent sentinel; see the error
hierarchy in [Package Surface](package-surface.md).

### TTL contract

- `store(..., ttl=None)`: `None` is the permanent-value sentinel. A concrete
  TTL must be a positive integer; zero, negatives, floats, and bools raise
  `ValueError` uniformly across backends.
- `ttl(key)` returns non-negative seconds remaining, or `None` when the key is
  missing, has no TTL, or has already expired. A backend that cannot inspect
  remaining TTL (Memcached) may also return `None` for a live expiring key —
  callers must treat `None` as "no observable live TTL".
- `list_storage_keys()` is deliberately separate from `clear_storage`. Backends
  that cannot safely enumerate their owned namespace keep the default
  `NotImplementedError`; callers must never emulate listing by clearing or
  guessing physical keys.

## Capability matrix

Which interfaces each bundled backend implements, from the backend registry
(the single source of truth):

| Backend | Queue | Set | Storage |
| ------- | ----- | --- | ------- |
| `redis` | Yes | Yes | Yes |
| `mongodb` | Yes | Yes | Yes |
| `elasticsearch` | Yes | Yes | Yes |
| `kafka` | Yes | — | — |
| `rabbitmq` | Yes | — | — |
| `rocketmq` | Yes | — | — |
| `pulsar` | Yes | — | — |
| `sqs` | Yes | — | — |
| `memcached` | — | — | Yes |
| `dynamodb` | — | — | Yes |

`—` means the backend does not implement the interface; configuring it for
that component fails at config time with `ConfigurationError`.

The `QUEUE_CAPABLE_BACKENDS` / `SET_CAPABLE_BACKENDS` /
`STORAGE_CAPABLE_BACKENDS` constants in `scrapy_extension.backends.connectors`
are bundled-only snapshots (importing them never triggers plugin discovery).
Installed third-party capabilities are visible only through
`capable_backends(capability)` or `get_registry()`. Per-backend maturity and
mode details: [STABILITY.md](../../.github/STABILITY.md).
