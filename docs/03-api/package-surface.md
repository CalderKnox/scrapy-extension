# Public Package Surface

What `import scrapy_extension` guarantees. Public surface is determined by the
owning namespace — names in a package's or subpackage's `__all__`, plus fully
qualified symbols explicitly listed in
[STABILITY.md](../../.github/STABILITY.md), which also assigns each name a
stability tier.

## Import mechanics

- `import scrapy_extension` requires **no** optional backend dependency. Core
  contracts, components, dedup filters and strategies, monitoring, and the
  exception hierarchy are imported eagerly.
- The ten backend classes and their settings/mode classes load lazily on first
  attribute access (PEP 562 module `__getattr__`); `dir(scrapy_extension)`
  lists them without importing anything.
- Accessing a lazy name with its optional dependency missing raises
  `ImportError` with `pip install scrapy-extension[<extra>]`. An `ImportError`
  that is not a genuine missing dependency — a real bug inside the backend
  module — is re-raised with its original chain instead of being masked as an
  install hint.
- `scrapy_extension.__version__` reads the installed distribution metadata
  (`"0.0.0"` when the package is not installed).

## Eager exports

| Group | Names |
| ----- | ----- |
| Interfaces | `Backend`, `QueueBackend`, `SetBackend`, `StorageBackend`, `Serializer`, `JSONSerializer`, `BackendType` |
| Components | `BackendScheduler`, `BackendDupeFilter`, `BackendPipeline`, `BackendQueue`, `BackendSpiderMixin` |
| Connection | `ConnectionManager`, `resolve_backend_config` |
| Configuration | `Settings` |
| Dedup filters & strategies | `MembershipFilter`, `MemoryMembershipFilter`, `SetMembershipFilter`, `BloomMembershipFilter`, `CuckooMembershipFilter`, `FilterFull`, `DedupeStrategy`, `build_membership_filter` |
| Monitoring | `Monitor`, `NullMonitor`, `ScrapyStatsMonitor` |
| Exceptions | `BackendError`, `BackendConnectionError`, `BackendOperationTimeout`, `ConfigurationError`, `QueueError`, `QueueOutcomeIndeterminateError`, `SerializationError`, `SetOutcomeIndeterminateError`, `StorageBackpressureError`, `StorageError`, `StorageOutcomeIndeterminateError` |

Component construction contracts (which factory each component provides) are
tabulated in the [project README](../../README.md).

## Lazy exports (require the matching extra)

Each backend contributes a backend class, a settings class, and a mode enum;
Kafka and SQS additionally export a topic/queue name-generation enum.

| Extra | Lazy names |
| ----- | ---------- |
| `dynamodb` | `DynamoDBBackend`, `DynamoDBSettings`, `DynamoDBMode` |
| `elasticsearch` | `ElasticSearchBackend`, `ElasticSearchSettings`, `ElasticSearchMode` |
| `kafka` | `KafkaBackend`, `KafkaSettings`, `KafkaMode`, `KafkaTopicNameGeneration` |
| `memcached` | `MemcachedBackend`, `MemcachedSettings`, `MemcachedMode` |
| `mongodb` | `MongoDBBackend`, `MongoDBSettings`, `MongoDBMode` |
| `pulsar` | `PulsarBackend`, `PulsarSettings`, `PulsarMode` |
| `rabbitmq` | `RabbitMQBackend`, `RabbitMQSettings`, `RabbitMQMode` |
| `redis` | `RedisBackend`, `RedisSettings`, `RedisMode` |
| `rocketmq` | `RocketMQBackend`, `RocketMQSettings`, `RocketMQMode` |
| `sqs` | `SqsBackend`, `SqsSettings`, `SqsMode`, `SqsQueueNameGeneration` |

## Backend registry

`scrapy_extension.backends.registry` holds one descriptor table plus
entry-point discovery for third-party backends:

- `BackendDescriptor` — frozen dataclass of `backend_type: str`,
  `backend_cls_path: str`, `settings_cls_path: str`, and
  `capabilities: frozenset[str]` (subset of `{"queue", "set", "storage"}`).
  Class fields are dotted-path **strings**, never imported classes — building
  the registry imports no backend module.
- `get_registry()` — memoized merged table (bundled + discovered
  entry-points); returns a fresh copy on every call. Bundled descriptors win
  name conflicts with a warning; two third-party plugins claiming one name are
  both rejected; a broken registration callable is skipped and logged.
  Discovery is single-flight under concurrency.
- `get_descriptor(backend_type)` — the descriptor, or `ConfigurationError`
  whose message lists bundled keys only (installed plugin metadata is not
  disclosed on the error path). Accepts a `BackendType` member.
- `has_capability(backend_type, capability)` — predicate returning `False`
  (never raising) for unknown backends.

Entry-point registration (group `scrapy_extension.backends`, name pattern
`^[a-z][a-z0-9_]*$`) is **Experimental**; the authoring contract is
[Backend Plugins](../06-guides/developer-guides/backend-plugins.md).

## Connection management

`scrapy_extension.backends.connectors` — constructed as
`ConnectionManager(backend_type, backend_settings)`:

- `ConnectionManager` — **Stable** shared pool keyed by
  `backend_type:settings_digest`; every `get_manager()` acquisition requires
  exactly one `close()` release.
- Component accessors `get_queue_backend()` / `get_set_backend()` /
  `get_storage_backend()` return the interface objects; a capability mismatch
  fails fast with `ConfigurationError` (see the capability matrix in
  [Backend Interfaces](backend-interfaces.md)).
- `resolve_backend_config(settings, type_key, settings_key, *,
  required_capabilities=None, component_name="")` — **Stable** fully qualified
  import used by all component factories. Backend-type precedence: Scrapy
  per-component, Scrapy global, environment per-component, environment global,
  then `"redis"`. An empty `SCRAPY_BACKEND_TYPE` counts as unset.
- **Experimental** additions: `acquire_lease()` / `ConnectionManagerLease` /
  `release_manager_acquire()`, and `apply_scrapy_breaker_policy()`.

## Error hierarchy

Every package exception derives from `BackendError`, so
`except BackendError` catches all backend-path failures uniformly.

```text
BackendError
├── BackendOperationTimeout          .operation, .timeout
├── BackendConnectionError           .backend_type, .message
│   └── SetOutcomeIndeterminateError
├── QueueError                       .queue_name, .operation
│   └── QueueOutcomeIndeterminateError
├── StorageError                     .operation, .key
│   ├── StorageOutcomeIndeterminateError
│   └── StorageBackpressureError     fixed message; item was never accepted
├── SerializationError               .data (None on terminal failures), .serializer
└── ConfigurationError               .setting_name, .setting_value
```

- Context attributes are redacted before the exception is built; sensitive
  values never survive on the exception object.
- `*OutcomeIndeterminateError` subclasses mean a mutation *may* have committed
  before its response was lost — callers must reconcile, not retry blindly.
- `ConfigurationError.setting_value` is automatically redacted to
  `***REDACTED***` when the value is a `SecretStr`/`SecretBytes` or the
  setting name contains a sensitive fragment.
- Configuration failures split by source: pydantic `ValidationError` for field
  type/range/enum violations; `ConfigurationError` for cross-field,
  capability, and unknown-name failures (including an unknown
  `SCRAPY_BACKEND_TYPE`).
