"""Every bundled queue backend rejects a pop timeout that cannot expire."""

from __future__ import annotations

import pytest

from scrapy_extension.backends.elasticsearch import ElasticSearchBackend
from scrapy_extension.backends.kafka import KafkaBackend
from scrapy_extension.backends.mongodb import MongoDBBackend
from scrapy_extension.backends.pulsar import PulsarBackend
from scrapy_extension.backends.rabbitmq import RabbitMQBackend
from scrapy_extension.backends.rocketmq import RocketMQBackend
from scrapy_extension.settings import (
    ElasticSearchSettings,
    KafkaSettings,
    MongoDBSettings,
    PulsarSettings,
    RabbitMQSettings,
    RocketMQSettings,
)

_INVALID_TIMEOUTS = (
    True,
    False,
    -1.0,
    float("nan"),
    float("inf"),
    float("-inf"),
)

_BACKENDS = (
    ("rabbitmq", lambda: RabbitMQBackend(RabbitMQSettings())),
    ("kafka", lambda: KafkaBackend(KafkaSettings())),
    ("rocketmq", lambda: RocketMQBackend(RocketMQSettings())),
    ("pulsar", lambda: PulsarBackend(PulsarSettings())),
    ("mongodb", lambda: MongoDBBackend(MongoDBSettings())),
    ("elasticsearch", lambda: ElasticSearchBackend(ElasticSearchSettings())),
)


@pytest.mark.parametrize(
    ("_name", "factory"), _BACKENDS, ids=[name for name, _factory in _BACKENDS]
)
@pytest.mark.parametrize("timeout", _INVALID_TIMEOUTS)
def test_pop_rejects_non_expiring_timeout(_name: str, factory, timeout: float) -> None:
    backend = factory()

    with pytest.raises(ValueError, match="finite non-negative"):
        backend.pop("jobs", timeout=timeout)


@pytest.mark.parametrize(
    ("_name", "factory"), _BACKENDS, ids=[name for name, _factory in _BACKENDS]
)
@pytest.mark.parametrize("timeout", (True, -1.0, float("nan"), float("inf")))
def test_pop_with_ack_rejects_non_expiring_timeout(
    _name: str, factory, timeout: float
) -> None:
    backend = factory()

    with pytest.raises(ValueError, match="finite non-negative"):
        backend.pop_with_ack("jobs", timeout=timeout)


def test_kafka_rejects_timeout_that_overflows_poll_milliseconds() -> None:
    backend = KafkaBackend(KafkaSettings())

    with pytest.raises(ValueError, match="finite non-negative"):
        backend.pop("jobs", timeout=1e308)
