# Backend matrix

- **Status:** active
- **Owner:** scrapy-extension maintainers
- **Last reviewed:** 2026-09-14
- **Related:** [backend interfaces](../03-api/backend-interfaces.md), [package surface](../03-api/package-surface.md)

## Summary

Lookup table for the ten bundled backend implementations and the capabilities they expose.

## Reference

| Backend key | Class | Optional extra | Queue | Set / dedup | Storage | Modes | Delivery semantics |
| --- | --- | --- |:---:|:---:|:---:| --- | --- |
| `redis` | `RedisBackend` | `redis` | ✓ | ✓ | ✓ | `standalone`, `master_slave` (deprecated), `sentinel`, `cluster` | Atomic pop; priority supported |
| `mongodb` | `MongoDBBackend` | `mongodb` | ✓ | ✓ | ✓ | `standalone`, `replica_set`, `sharded_cluster`, `atlas` | Atomic pop; priority supported |
| `elasticsearch` | `ElasticSearchBackend` | `elasticsearch` | ✓ | ✓ | ✓ | `standalone`, `cloud` | Atomic pop; priority supported |
| `kafka` | `KafkaBackend` | `kafka` | ✓ | — | — | `standalone`, `cluster`, `confluent` | Deferred ack; priority is partition-based |
| `rabbitmq` | `RabbitMQBackend` | `rabbitmq` | ✓ | — | — | `standalone`, `cluster`, `mirrored_queues` | Deferred ack; priority supported |
| `rocketmq` | `RocketMQBackend` | `rocketmq` | ✓ | — | — | `standalone` | Deferred ack; priority is not guaranteed |
| `pulsar` | `PulsarBackend` | `pulsar` | ✓ | — | — | `standalone`, `cluster` | Deferred ack; priority ignored |
| `sqs` | `SqsBackend` | `sqs` | ✓ | — | — | `standalone` (LocalStack), `cloud` | Deferred ack; priority ignored |
| `memcached` | `MemcachedBackend` | `memcached` | — | — | ✓ | `standalone` | KV with TTL; no queue or set |
| `dynamodb` | `DynamoDBBackend` | `dynamodb` | — | — | ✓ | `standalone` (LocalStack), `cloud` | KV with application-level TTL |

Install only what the deployment uses, for example `pip install 'scrapy-extension[redis]'`; `all` installs every optional adapter. Core imports do not load optional dependencies. Queue-only backends cannot be selected for set or storage components; bind them with `SCRAPY_QUEUE_BACKEND_TYPE`.

All bundled queue backends declare concurrent-ack support. A third-party deferred-ack backend must explicitly declare this capability when `CONCURRENT_REQUESTS > 1`.

## Examples

```bash
pip install 'scrapy-extension[redis,mongodb,elasticsearch]'
```
