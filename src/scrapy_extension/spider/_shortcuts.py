"""Backend shortcut-settings builders, hoisted out of ``BackendSpiderMixin``.

P3-4 L4 (R144): these pure attribute-to-dict builders lived inside the
3014-line mixin for no mixin-specific reason. Each takes the spider (any
object carrying the shortcut attributes) and returns only the shortcuts
that were explicitly set — ``None`` attributes contribute nothing, which
keeps per-backend settings models on their defaults.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

__all__ = ["BACKEND_SHORTCUT_BUILDERS"]


def build_redis_shortcuts(source: Any) -> dict[str, Any]:
    """Build Redis-specific shortcut settings."""
    shortcuts: dict[str, Any] = {}
    if source.redis_host is not None:
        shortcuts["host"] = source.redis_host
    if source.redis_port is not None:
        shortcuts["port"] = source.redis_port
    if source.redis_db is not None:
        shortcuts["db"] = source.redis_db
    if source.redis_password is not None:
        shortcuts["password"] = source.redis_password
    return shortcuts


def build_mongodb_shortcuts(source: Any) -> dict[str, Any]:
    """Build MongoDB-specific shortcut settings."""
    shortcuts: dict[str, Any] = {}
    if source.mongodb_uri is not None:
        shortcuts["uri"] = source.mongodb_uri
    if source.mongodb_db is not None:
        shortcuts["database"] = source.mongodb_db
    return shortcuts


def build_kafka_shortcuts(source: Any) -> dict[str, Any]:
    """Build Kafka-specific shortcut settings."""
    shortcuts: dict[str, Any] = {}
    if source.kafka_bootstrap_servers is not None:
        shortcuts["bootstrap_servers"] = source.kafka_bootstrap_servers
    return shortcuts


def build_rabbitmq_shortcuts(source: Any) -> dict[str, Any]:
    """Build RabbitMQ-specific shortcut settings."""
    shortcuts: dict[str, Any] = {}
    if source.rabbitmq_url is not None:
        shortcuts["url"] = source.rabbitmq_url
    return shortcuts


def build_elasticsearch_shortcuts(source: Any) -> dict[str, Any]:
    """Build ElasticSearch-specific shortcut settings."""
    shortcuts: dict[str, Any] = {}
    if source.elasticsearch_hosts is not None:
        shortcuts["hosts"] = source.elasticsearch_hosts
    if source.elasticsearch_cloud_id is not None:
        shortcuts["cloud_id"] = source.elasticsearch_cloud_id
    if source.elasticsearch_api_key is not None:
        shortcuts["api_key"] = source.elasticsearch_api_key
    return shortcuts


def build_rocketmq_shortcuts(source: Any) -> dict[str, Any]:
    """Build RocketMQ-specific shortcut settings."""
    shortcuts: dict[str, Any] = {}
    if source.rocketmq_namesrv_address is not None:
        shortcuts["namesrv_address"] = source.rocketmq_namesrv_address
    if source.rocketmq_access_key is not None:
        shortcuts["access_key"] = source.rocketmq_access_key
    if source.rocketmq_secret_key is not None:
        shortcuts["secret_key"] = source.rocketmq_secret_key
    if source.rocketmq_tls_enabled is not None:
        shortcuts["tls_enabled"] = source.rocketmq_tls_enabled
    return shortcuts


# Map of backend value -> shortcut builder. The flat dispatch keeps
# ``_build_backend_settings`` free of per-backend branching as backends are
# added. Backends without shortcut attributes (Pulsar, SQS, Memcached,
# DynamoDB) have no entry and contribute nothing.
BACKEND_SHORTCUT_BUILDERS: Mapping[str, Callable[[Any], dict[str, Any]]] = {
    "redis": build_redis_shortcuts,
    "mongodb": build_mongodb_shortcuts,
    "kafka": build_kafka_shortcuts,
    "rabbitmq": build_rabbitmq_shortcuts,
    "elasticsearch": build_elasticsearch_shortcuts,
    "rocketmq": build_rocketmq_shortcuts,
}
