"""Configuration module for scrapy-extension.

This module provides pydantic-settings based configuration classes
for all backend types.

``Settings`` (the core contract) stays eager. Every backend-specific
settings class loads on first attribute access (PEP 562) so importing
this package — and every ``settings.<submodule>`` import that lands here
first — no longer pays for all sixteen submodules up front. The
TYPE_CHECKING block below keeps the static exports visible to mypy;
``from scrapy_extension.settings import RedisSettings`` and friends
resolve through ``__getattr__`` at runtime.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from scrapy_extension.settings.base import Settings

if TYPE_CHECKING:
    from scrapy_extension.settings.dynamodb import (
        DynamoDBMode as DynamoDBMode,
    )
    from scrapy_extension.settings.dynamodb import (
        DynamoDBSettings as DynamoDBSettings,
    )
    from scrapy_extension.settings.elasticsearch import (
        ElasticSearchMode as ElasticSearchMode,
    )
    from scrapy_extension.settings.elasticsearch import (
        ElasticSearchSettings as ElasticSearchSettings,
    )
    from scrapy_extension.settings.kafka import (
        KafkaMode as KafkaMode,
    )
    from scrapy_extension.settings.kafka import (
        KafkaSettings as KafkaSettings,
    )
    from scrapy_extension.settings.kafka import (
        KafkaTopicNameGeneration as KafkaTopicNameGeneration,
    )
    from scrapy_extension.settings.memcached import (
        MemcachedMode as MemcachedMode,
    )
    from scrapy_extension.settings.memcached import (
        MemcachedSettings as MemcachedSettings,
    )
    from scrapy_extension.settings.mongodb import (
        MongoDBMode as MongoDBMode,
    )
    from scrapy_extension.settings.mongodb import (
        MongoDBSettings as MongoDBSettings,
    )
    from scrapy_extension.settings.pulsar import (
        PulsarMode as PulsarMode,
    )
    from scrapy_extension.settings.pulsar import (
        PulsarSettings as PulsarSettings,
    )
    from scrapy_extension.settings.rabbitmq import (
        RabbitMQMode as RabbitMQMode,
    )
    from scrapy_extension.settings.rabbitmq import (
        RabbitMQSettings as RabbitMQSettings,
    )
    from scrapy_extension.settings.redis import (
        RedisMode as RedisMode,
    )
    from scrapy_extension.settings.redis import (
        RedisSettings as RedisSettings,
    )
    from scrapy_extension.settings.rocketmq import (
        RocketMQMode as RocketMQMode,
    )
    from scrapy_extension.settings.rocketmq import (
        RocketMQSettings as RocketMQSettings,
    )
    from scrapy_extension.settings.sqs import (
        SqsMode as SqsMode,
    )
    from scrapy_extension.settings.sqs import (
        SqsQueueNameGeneration as SqsQueueNameGeneration,
    )
    from scrapy_extension.settings.sqs import (
        SqsSettings as SqsSettings,
    )


# Lazy exports: name -> owning module. Keys only; no submodule is imported
# by merely listing it.
_LAZY_EXPORTS: dict[str, str] = {
    "DynamoDBMode": "scrapy_extension.settings.dynamodb",
    "DynamoDBSettings": "scrapy_extension.settings.dynamodb",
    "ElasticSearchMode": "scrapy_extension.settings.elasticsearch",
    "ElasticSearchSettings": "scrapy_extension.settings.elasticsearch",
    "KafkaMode": "scrapy_extension.settings.kafka",
    "KafkaSettings": "scrapy_extension.settings.kafka",
    "KafkaTopicNameGeneration": "scrapy_extension.settings.kafka",
    "MemcachedMode": "scrapy_extension.settings.memcached",
    "MemcachedSettings": "scrapy_extension.settings.memcached",
    "MongoDBMode": "scrapy_extension.settings.mongodb",
    "MongoDBSettings": "scrapy_extension.settings.mongodb",
    "PulsarMode": "scrapy_extension.settings.pulsar",
    "PulsarSettings": "scrapy_extension.settings.pulsar",
    "RabbitMQMode": "scrapy_extension.settings.rabbitmq",
    "RabbitMQSettings": "scrapy_extension.settings.rabbitmq",
    "RedisMode": "scrapy_extension.settings.redis",
    "RedisSettings": "scrapy_extension.settings.redis",
    "RocketMQMode": "scrapy_extension.settings.rocketmq",
    "RocketMQSettings": "scrapy_extension.settings.rocketmq",
    "SqsMode": "scrapy_extension.settings.sqs",
    "SqsQueueNameGeneration": "scrapy_extension.settings.sqs",
    "SqsSettings": "scrapy_extension.settings.sqs",
}

_SETTINGS_SUBMODULES: frozenset[str] = frozenset(
    {
        "_aws",
        "_broker_endpoints",
        "_endpoint_validation",
        "_redacted",
        "_transport_security",
        "base",
        "dynamodb",
        "elasticsearch",
        "kafka",
        "memcached",
        "mongodb",
        "pulsar",
        "rabbitmq",
        "redis",
        "rocketmq",
        "sqs",
    }
)

__all__ = ["Settings", *_LAZY_EXPORTS]


def __getattr__(name: str) -> object:
    """Resolve one backend settings class or submodule lazily (PEP 562)."""
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is not None:
        return getattr(import_module(module_path), name)
    if name in _SETTINGS_SUBMODULES:
        # ``from scrapy_extension.settings import redis`` and direct attribute
        # access keep working without pre-importing every sibling.
        return import_module(f"scrapy_extension.settings.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """PEP 562 companion — lazy names stay visible to dir() and autocomplete."""
    return sorted(set(globals()) | set(_LAZY_EXPORTS) | set(_SETTINGS_SUBMODULES))
