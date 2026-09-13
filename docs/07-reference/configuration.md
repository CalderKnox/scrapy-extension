# Configuration reference

- **Status:** active
- **Owner:** scrapy-extension maintainers
- **Last reviewed:** 2026-09-14
- **Related:** [migration guide](../06-guides/user-guides/migration-guide.md), [runbook](../05-runbooks/runbook.md), `scrapy_extension.settings`

## Summary

Environment-variable and settings-model lookup for the global controls shared by all components.

## Reference

`Settings` uses the `SCRAPY_` prefix (case-insensitive), rejects unknown constructor fields, and supports environment-variable loading. Backend settings use their own prefix: `SCRAPY_REDIS_`, `SCRAPY_MONGO_`, `SCRAPY_KAFKA_`, `SCRAPY_RABBITMQ_`, `SCRAPY_ELASTICSEARCH_`, `SCRAPY_ROCKETMQ_`, `SCRAPY_PULSAR_`, `SCRAPY_MEMCACHED_`, `SCRAPY_SQS_`, and `SCRAPY_DYNAMODB_`.

### Global settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `SCRAPY_BACKEND_TYPE` | `redis` | Fallback backend for queue, set, and storage. |
| `SCRAPY_SERIALIZER` | `json` | Wire serializer; currently JSON only. |
| `SCRAPY_RETRY_ATTEMPTS` / `SCRAPY_RETRY_DELAY` | `3` / `1.0` | Connection-establishment retry policy. |
| `SCRAPY_REACTOR_IO_TIMEOUT` | package default | Lifecycle and acknowledgement wait budget. |
| `SCRAPY_QUEUE_MAX_ITEM_BYTES` / `SCRAPY_PIPELINE_MAX_ITEM_BYTES` | `1048576` | Serialized request/item limits. |
| `SCRAPY_DEDUP_STRATEGY` | `set` | `set`, `memory`, `bloom`, or `cuckoo`; local filters are per-process. |
| `SCRAPY_QUEUE_STRATEGY` | `immediate` | Queue scheduling strategy (see queue strategy guide). |
| `SCRAPY_STORAGE_STRATEGY` | `passthrough` | `passthrough` or `batched`. |
| `SCRAPY_PIPELINE_MAX_STORAGE_ERRORS` | `10` | Consecutive store failures before surfacing an error; `None` opts into loss. |
| `SCRAPY_CIRCUIT_BREAKER_ENABLED` | `false` | Opt-in fail-fast breaker for backend operations. |
| `SCRAPY_CIRCUIT_BREAKER_FAILURE_THRESHOLD` / `...RESET_TIMEOUT` | `5` / `30.0` | Breaker trip count and half-open delay. |
| `SCRAPY_BACKPRESSURE_PAUSE_AT` / `...RESUME_AT` | unset | Queue-depth hysteresis; unset disables throttling. |
| `SCRAPY_QUEUE_DEPTH_SAMPLE_EVERY` | `100` | Pop operations between depth probes. |
| `SCRAPY_QUEUE_DELAY_MAX_HELD` | `100000` | Warning threshold for delayed in-process items. |
| `SCRAPY_MONITOR_BACKPRESSURE_THRESHOLD` / `...POP_RATE_WINDOW_S` | `1000` / `60.0` | Monitoring signal thresholds. |

### Component-specific backend selection

`SCRAPY_QUEUE_BACKEND_TYPE`, `SCRAPY_SET_BACKEND_TYPE`, and `SCRAPY_STORAGE_BACKEND_TYPE` override the global backend independently. Matching `..._BACKEND_SETTINGS` values provide the serialized settings payload. Resolution precedence is Scrapy per-component, Scrapy global, environment per-component, environment global, then `redis`.

### Security rules

Remote plaintext or HTTP endpoints are denied by default. Each adapter has an explicit opt-in (`...ALLOW_REMOTE_PLAINTEXT` or `...ALLOW_REMOTE_HTTP`); use TLS/authentication in production. Secret fields (`password`, keys, tokens, URLs containing credentials) are redacted in settings representations and configuration errors.

### Per-backend entry points

| Prefix | Important fields |
| --- | --- |
| `SCRAPY_REDIS_` | `MODE`, `HOST`, `PORT`, `DB`, `NAMESPACE`, Sentinel/Cluster and TLS fields |
| `SCRAPY_MONGO_` | `MODE`, `URI`, `DATABASE`, collection names, replica/sharded, auth and TLS fields |
| `SCRAPY_KAFKA_` | `MODE`, broker lists, security/SASL/SSL, consumer group, topic generation |
| `SCRAPY_RABBITMQ_` | `MODE`, URL/host credentials, cluster nodes, TLS, queue durability and prefetch |
| `SCRAPY_ELASTICSEARCH_` | `MODE`, `HOSTS` or `CLOUD_ID`, API/basic auth, TLS, queue/set/storage indices |
| `SCRAPY_ROCKETMQ_` | `NAMESRV_ADDRESS`, credentials, TLS, consumer group, message and visibility limits |
| `SCRAPY_PULSAR_` | `SERVICE_URL`, subscription/consumer type, auth token and TLS |
| `SCRAPY_MEMCACHED_` | `HOST`, `PORT`, timeouts, `ALLOW_FLUSH_ALL` |
| `SCRAPY_SQS_` | `MODE`, region/endpoint, AWS credentials, queue-name generation, visibility timeout |
| `SCRAPY_DYNAMODB_` | `MODE`, table/region/endpoint, AWS credentials, legacy-clear override |

## Examples

```bash
SCRAPY_QUEUE_BACKEND_TYPE=redis
SCRAPY_SET_BACKEND_TYPE=mongodb
SCRAPY_STORAGE_BACKEND_TYPE=elasticsearch
SCRAPY_REDIS_NAMESPACE=my-crawler
```
