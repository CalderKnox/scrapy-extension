"""Backend type identity and policy ceilings — the dependency-free leaf.

P3-1 (R144): ``settings/base.py`` imported ``BackendType`` and
``CIRCUIT_BREAKER_MAX_RESET_TIMEOUT_S`` from ``backends``, executing the
backend package graph during settings import (the settings<->backends
cycle). Types and policy constants shared across the layer boundary live
in this leaf module; ``backends.base`` and ``backends.circuit_breaker``
re-export their former names, so every existing import keeps working.
"""

from __future__ import annotations

from enum import Enum

from scrapy_extension.exceptions.base import _looks_sensitive_text

__all__ = ["CIRCUIT_BREAKER_MAX_RESET_TIMEOUT_S", "BackendType"]


class BackendType(str, Enum):
    """Supported backend types for distributed crawling.

    Attributes:
        REDIS: Redis backend for distributed crawling.
        MONGODB: MongoDB backend for distributed crawling.
        KAFKA: Kafka backend for distributed crawling.
        RABBITMQ: RabbitMQ backend for distributed crawling.
        ELASTICSEARCH: ElasticSearch backend for distributed crawling.
        ROCKETMQ: RocketMQ backend for distributed crawling.
        PULSAR: Pulsar backend for distributed crawling (queue-only).
        MEMCACHED: Memcached backend (StorageBackend — KV with TTL).
        SQS: Amazon SQS backend (queue-only MQ).
        DYNAMODB: DynamoDB backend (StorageBackend — NoSQL KV).
    """

    REDIS = "redis"
    MONGODB = "mongodb"
    KAFKA = "kafka"
    RABBITMQ = "rabbitmq"
    ELASTICSEARCH = "elasticsearch"
    ROCKETMQ = "rocketmq"
    PULSAR = "pulsar"
    MEMCACHED = "memcached"
    SQS = "sqs"
    DYNAMODB = "dynamodb"

    @classmethod
    def _missing_(cls, value: object) -> BackendType | None:
        """Reject unknown values with a descriptive error.

        Round-14 R14-B note: USER-FACING backend-type validation is routed
        through ``Settings._validate_backend_type`` (a ``field_validator``),
        which accepts ANY registry-known 3rd-party string AND raises
        ``ConfigurationError`` (the project's config-error family) for unknown
        values — never pydantic ``ValidationError``. This ``_missing_`` hook
        is a DEFENSIVE backstop for direct ``BackendType(x)`` calls that
        bypass the settings layer (e.g. internal code paths). It keeps the
        conventional ``ValueError`` for low-level callers; operators hitting
        this path through ``Settings`` see ``ConfigurationError`` instead
        (see ``settings/base.py::_validate_backend_type``).

        Args:
            value: The value that did not match any member.

        Raises:
            ValueError: Always — ``_missing_`` must return ``None`` or a
                member; we choose to raise for fail-fast UX.
        """
        valid = ", ".join(repr(member.value) for member in cls)
        # Values reaching this backstop can echo credential-shaped text into
        # the error message; keep the leaf dependency-free by using the
        # exception layer's structural sensitivity probe (not repr) for them.
        rendered = (
            "<redacted>"
            if type(value) is str and _looks_sensitive_text(value)
            else repr(value)
        )
        msg = f"{rendered} is not a valid {cls.__name__}. Valid values: {valid}."
        raise ValueError(msg)


# Policy ceiling (reject, not clamp): an OPEN breaker must always be able to
# recover, so the reset timeout is bounded even for pathological configs.
CIRCUIT_BREAKER_MAX_RESET_TIMEOUT_S: float = 3600.0
