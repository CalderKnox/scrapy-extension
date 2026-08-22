"""Coverage closure for bundled settings validator rejection branches (w2 pack).

Targets the defensive ``ConfigurationError`` branches of the bundled settings
surfaces that the configuration suites leave cold: unsupported-mode guards on
model validators (reached only after model mutation), strict host/endpoint
grammars, credential typing, TLS opt-in contracts, and the canonical scalar
normalizers. Every case is a pure validation call — no client construction,
no network.
"""

from __future__ import annotations

from typing import Any

import pytest

from scrapy_extension.exceptions import ConfigurationError
from scrapy_extension.settings.elasticsearch import (
    ElasticSearchMode,
    ElasticSearchSettings,
    _has_safe_host_percent_encoding,
)
from scrapy_extension.settings.kafka import (
    KafkaMode,
    _kafka_credential_value,
    _kafka_policy_int,
    validate_kafka_authentication,
    validate_kafka_confluent_client_contract,
    validate_kafka_transport_security,
)
from scrapy_extension.settings.memcached import (
    MemcachedMode,
    normalize_memcached_flush_setting,
    validate_memcached_connection,
)
from scrapy_extension.settings.mongodb import (
    MongoDBMode,
    MongoDBSettings,
    _normalize_mongodb_seed_host,
    _validate_mongodb_uri_authority,
    is_mongodb_direct_loopback_uri,
    validate_mongodb_database,
    validate_mongodb_transport_security,
    validate_mongodb_uri,
)
from scrapy_extension.settings.pulsar import (
    _auth_token_value,
    validate_pulsar_connection,
)
from scrapy_extension.settings.rabbitmq import (
    RabbitMQMode,
    RabbitMQSettings,
    _decode_rabbitmq_virtual_host,
    _secret_text,
    parse_rabbitmq_node,
    validate_rabbitmq_virtual_host,
)
from scrapy_extension.settings.redis import (
    RedisMode,
    RedisSettings,
    normalize_redis_host,
    parse_redis_endpoint,
    validate_redis_tls,
    validate_redis_transport_security,
)
from scrapy_extension.settings.rocketmq import (
    RocketMQMode,
    _credential_value,
    _rocketmq_namesrv_endpoints_are_loopback,
    validate_rocketmq_connection,
)

# ---------------------------------------------------------------------------
# Elasticsearch
# ---------------------------------------------------------------------------


def test_es_zone_id_encoding_rejects_invalid_zone_literals() -> None:
    assert _has_safe_host_percent_encoding("host", None) is True
    # A zone-bearing IPv6 literal whose zone fails RFC 6874 grammar.
    assert (
        _has_safe_host_percent_encoding("[fe80::1%25bad!zone]", "fe80::1%25bad!zone")
        is False
    )
    assert _has_safe_host_percent_encoding("[fe80::1%25]", "fe80::1%25") is False


def test_es_mode_guards_reject_mutated_mode_on_every_validator() -> None:
    settings = ElasticSearchSettings()
    for validator in (
        "_validate_hosts_scheme",
        "validate_mode_requirements",
        "_validate_no_cleartext_credentials",
        "_validate_tls_verification_and_intent",
        "_require_remote_unauthenticated_plaintext_opt_in",
    ):
        settings = ElasticSearchSettings()
        settings.mode = "not-a-mode"  # type: ignore[assignment]
        with pytest.raises(ConfigurationError, match="mode is unsupported"):
            getattr(settings, validator)()


def test_es_host_guards_reject_non_list_hosts_after_mutation() -> None:
    for validator in (
        "_validate_hosts_scheme",
        "_validate_no_cleartext_credentials",
        "_validate_tls_verification_and_intent",
        "_require_remote_unauthenticated_plaintext_opt_in",
    ):
        settings = ElasticSearchSettings()
        settings.hosts = "redis://localhost:6379"  # type: ignore[assignment]
        with pytest.raises(ConfigurationError, match="hosts must be a list"):
            getattr(settings, validator)()


def test_es_auth_completeness_rejects_plain_credential_values() -> None:
    # model_construct bypasses the secret-wrapping __setattr__, publishing the
    # raw values the validator must reject.
    settings = ElasticSearchSettings.model_construct(api_key="raw-api-key")
    with pytest.raises(ConfigurationError, match="api_key must be a string"):
        settings._validate_auth_completeness()

    settings = ElasticSearchSettings.model_construct(password="raw-password")
    with pytest.raises(ConfigurationError, match="password must be a string"):
        settings._validate_auth_completeness()

    settings = ElasticSearchSettings()
    settings.username = 12345  # type: ignore[assignment]
    with pytest.raises(ConfigurationError, match="username must be a string"):
        settings._validate_auth_completeness()


def test_es_cloud_mode_rejects_non_string_cloud_id() -> None:
    settings = ElasticSearchSettings.model_construct(
        mode=ElasticSearchMode.CLOUD, cloud_id=12345
    )
    with pytest.raises(ConfigurationError, match="cloud_id must be a string"):
        settings.validate_mode_requirements()


def test_es_tls_intent_rejects_non_boolean_verification() -> None:
    settings = ElasticSearchSettings()
    settings.verify_certs = "yes"  # type: ignore[assignment]
    with pytest.raises(ConfigurationError, match="verify_certs must be a boolean"):
        settings._validate_tls_verification_and_intent()


# ---------------------------------------------------------------------------
# Kafka
# ---------------------------------------------------------------------------


def test_kafka_credential_value_rejects_opaque_types() -> None:
    with pytest.raises(ConfigurationError, match="must be a string"):
        _kafka_credential_value(12345, "sasl_username")


def test_kafka_authentication_rejects_unsupported_mode_and_mechanism() -> None:
    with pytest.raises(ConfigurationError, match="Kafka mode is unsupported"):
        validate_kafka_authentication(
            mode=12345,
            security_protocol="PLAINTEXT",
            sasl_mechanism=None,
            sasl_username=None,
            sasl_password=None,
            confluent_api_key=None,
            confluent_api_secret=None,
        )
    with pytest.raises(ConfigurationError, match="sasl_mechanism must be supported"):
        validate_kafka_authentication(
            mode=KafkaMode.STANDALONE,
            security_protocol="SASL_SSL",
            sasl_mechanism="NTLM",
            sasl_username=None,
            sasl_password=None,
            confluent_api_key=None,
            confluent_api_secret=None,
        )


def test_kafka_transport_security_rejects_mode_and_protocol_types() -> None:
    with pytest.raises(ConfigurationError, match="Kafka mode is unsupported"):
        validate_kafka_transport_security(
            mode=12345, security_protocol="PLAINTEXT", ssl_check_hostname=True
        )
    with pytest.raises(ConfigurationError, match="must be a supported Kafka protocol"):
        validate_kafka_transport_security(
            mode=KafkaMode.STANDALONE,
            security_protocol="SASL",
            ssl_check_hostname=True,
        )


def test_kafka_confluent_contract_rejects_unsupported_mode() -> None:
    with pytest.raises(ConfigurationError, match="Kafka mode is unsupported"):
        validate_kafka_confluent_client_contract(
            mode=12345,
            security_protocol="PLAINTEXT",
            ssl_cafile=None,
            ssl_certfile=None,
            ssl_keyfile=None,
        )


def test_kafka_policy_int_rejects_bools_and_low_values() -> None:
    with pytest.raises(ConfigurationError, match="must be an integer"):
        _kafka_policy_int(True, "batch_size", 1)


# ---------------------------------------------------------------------------
# Memcached
# ---------------------------------------------------------------------------


def test_memcached_remote_plaintext_requires_explicit_opt_in() -> None:
    with pytest.raises(ConfigurationError, match="unauthenticated plaintext protocol"):
        validate_memcached_connection(
            MemcachedMode.STANDALONE, "memcached.internal", 11211, False
        )

    with pytest.raises(ConfigurationError, match="allow_remote_plaintext must be"):
        validate_memcached_connection(
            MemcachedMode.STANDALONE, "localhost", 11211, "yes"
        )


def test_memcached_flush_setting_accepts_canonical_text() -> None:
    assert normalize_memcached_flush_setting(" True ") is True
    assert normalize_memcached_flush_setting("FALSE") is False


# ---------------------------------------------------------------------------
# Pulsar
# ---------------------------------------------------------------------------


def test_pulsar_auth_token_rejects_opaque_types() -> None:
    assert _auth_token_value("raw-token") == "raw-token"
    with pytest.raises(ConfigurationError, match="auth_token must be a string"):
        _auth_token_value(12345)


def test_pulsar_connection_rejects_malformed_service_urls() -> None:
    with pytest.raises(ConfigurationError, match="service_url must be a string"):
        validate_pulsar_connection(12345, None, None, False, True)

    with pytest.raises(ConfigurationError, match="single scheme"):
        validate_pulsar_connection("pulsar://", None, None, False, True)

    with pytest.raises(ConfigurationError, match="non-empty Pulsar endpoints"):
        validate_pulsar_connection("pulsar://,", None, None, False, True)


def test_pulsar_connection_rejects_invalid_tls_material_and_flags() -> None:
    with pytest.raises(ConfigurationError, match="tls_trust_certs_file must be"):
        validate_pulsar_connection("pulsar://localhost:6650", None, "  ", False, True)

    with pytest.raises(ConfigurationError, match="allow_insecure_connection"):
        validate_pulsar_connection("pulsar://localhost:6650", None, None, 12345, True)

    with pytest.raises(ConfigurationError, match="tls_validate_hostname"):
        validate_pulsar_connection("pulsar://localhost:6650", None, None, False, 12345)


def test_pulsar_authenticated_connection_requires_verified_transport() -> None:
    with pytest.raises(ConfigurationError, match=r"require 'pulsar\+ssl://'"):
        validate_pulsar_connection(
            "pulsar://localhost:6650", "token", None, False, True
        )

    # Loopback endpoints keep the remote-plaintext guard out of the way so the
    # authenticated-transport contracts are exercised directly.
    with pytest.raises(ConfigurationError, match="certificate verification"):
        validate_pulsar_connection(
            "pulsar+ssl://localhost:6651", "token", None, True, True
        )

    with pytest.raises(ConfigurationError, match="hostname verification"):
        validate_pulsar_connection(
            "pulsar+ssl://localhost:6651", "token", None, False, False
        )


# ---------------------------------------------------------------------------
# RocketMQ
# ---------------------------------------------------------------------------


def test_rocketmq_credential_value_rejects_opaque_types() -> None:
    assert _credential_value("raw", "access_key") == "raw"
    with pytest.raises(ConfigurationError, match="access_key must be a string"):
        _credential_value(12345, "access_key")


def test_rocketmq_namesrv_loopback_rejects_non_string_endpoints() -> None:
    assert _rocketmq_namesrv_endpoints_are_loopback(12345) is False


def test_rocketmq_connection_rejects_unsupported_mode() -> None:
    with pytest.raises(ConfigurationError, match="Unsupported RocketMQ mode"):
        validate_rocketmq_connection(
            mode="not-a-mode",  # type: ignore[arg-type]
            namesrv_address="localhost:9876",
            access_key=None,
            secret_key=None,
            tls_enabled=False,
        )

    with pytest.raises(ConfigurationError, match="tls_enabled must be a boolean"):
        validate_rocketmq_connection(
            mode=RocketMQMode.STANDALONE,
            namesrv_address="localhost:9876",
            access_key=None,
            secret_key=None,
            tls_enabled="yes",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# RabbitMQ
# ---------------------------------------------------------------------------


def test_rabbitmq_secret_text_only_accepts_known_secret_types() -> None:
    assert _secret_text(None) is None
    assert _secret_text("plain") == "plain"
    assert _secret_text(12345) is None


def test_rabbitmq_virtual_host_grammar_rejections() -> None:
    with pytest.raises(ConfigurationError, match="virtual_host must be"):
        validate_rabbitmq_virtual_host("bad vhost")

    with pytest.raises(ConfigurationError, match="invalid percent escape"):
        _decode_rabbitmq_virtual_host("%zz")

    with pytest.raises(ConfigurationError, match="virtual_host must be"):
        _decode_rabbitmq_virtual_host("bad vhost")


def test_rabbitmq_node_parser_rejects_invalid_default_port() -> None:
    with pytest.raises(ConfigurationError, match="port must be between"):
        parse_rabbitmq_node("amqp.internal:5672", default_port=0)


def test_rabbitmq_url_authority_grammar_rejections() -> None:
    with pytest.raises(ConfigurationError, match="ASCII AMQP authority"):
        RabbitMQSettings(url="amqp://ho st:5672/")

    with pytest.raises(ConfigurationError, match="valid 'amqp://' or 'amqps://'"):
        RabbitMQSettings(url="http://broker.internal:5672/")

    with pytest.raises(ConfigurationError, match="userinfo is not allowed"):
        RabbitMQSettings(url="amqp://user:pass@localhost:5672/")

    with pytest.raises(ConfigurationError, match="must include a host"):
        RabbitMQSettings(url="amqp:///")

    with pytest.raises(ConfigurationError, match="query or fragment"):
        RabbitMQSettings(url="amqp://localhost:5672/?heartbeat=10")


def test_rabbitmq_mode_requirements_reject_mutated_inputs() -> None:
    settings = RabbitMQSettings.model_construct(mode="not-a-mode")
    with pytest.raises(ConfigurationError, match="mode is unsupported"):
        settings._validate_mode_requirements()

    settings = RabbitMQSettings.model_construct(
        mode=RabbitMQMode.CLUSTER, cluster_nodes="localhost:5672"
    )
    with pytest.raises(ConfigurationError, match="list of host or host:port"):
        settings._validate_mode_requirements()


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


def test_redis_host_grammar_rejections() -> None:
    for bad_host in ("bad host", "[::1", "[127.0.0.1]", "host:extra:ports"):
        with pytest.raises(ConfigurationError):
            normalize_redis_host(bad_host)


def test_redis_endpoint_parser_rejects_malformed_brackets() -> None:
    for bad_endpoint in ("[::1", "[::1]]:6379", "[127.0.0.1]:6379", "[::1]:63]79"):
        with pytest.raises(ConfigurationError):
            parse_redis_endpoint(bad_endpoint, setting_name="sentinels", index=0)


def test_redis_tls_validator_rejects_non_boolean_flag() -> None:
    with pytest.raises(ConfigurationError, match="ssl_enabled must be a boolean"):
        validate_redis_tls(12345, None, None, None)  # type: ignore[arg-type]


def _redis_transport_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "mode": RedisMode.STANDALONE,
        "host": "localhost",
        "username": None,
        "password": None,
        "sentinel_username": None,
        "sentinel_password": None,
        "ssl_enabled": False,
        "ssl_cafile": None,
        "ssl_certfile": None,
        "ssl_keyfile": None,
        "ssl_check_hostname": True,
    }
    kwargs.update(overrides)
    return kwargs


def test_redis_transport_security_rejects_mode_and_flag_types() -> None:
    with pytest.raises(ConfigurationError, match="Redis mode is unsupported"):
        validate_redis_transport_security(
            **_redis_transport_kwargs(mode=12345, host=None)
        )
    with pytest.raises(
        ConfigurationError, match="ssl_check_hostname must be a boolean"
    ):
        validate_redis_transport_security(
            **_redis_transport_kwargs(ssl_check_hostname=12345)
        )


def test_redis_settings_endpoint_json_rejects_malformed_text() -> None:
    with pytest.raises(ConfigurationError, match="JSON endpoint list"):
        RedisSettings(sentinels="{not-json")

    # Valid JSON that is not an endpoint list is rejected after decoding.
    with pytest.raises(ConfigurationError, match="list of endpoints"):
        RedisSettings(sentinels='{"host": "localhost:6379"}')


def test_redis_mode_requirements_reject_mutated_inputs() -> None:
    settings = RedisSettings.model_construct(mode=12345)
    with pytest.raises(ConfigurationError, match="mode is unsupported"):
        settings.validate_mode_requirements()

    settings = RedisSettings.model_construct(sentinel_master_name=12345)
    with pytest.raises(
        ConfigurationError, match="sentinel_master_name must be a string"
    ):
        settings.validate_mode_requirements()

    settings = RedisSettings.model_construct(sentinels="localhost:6379")
    with pytest.raises(ConfigurationError, match="must be a list of endpoints"):
        settings.validate_mode_requirements()


def test_redis_db_and_replica_mutations_fail_closed() -> None:
    settings = RedisSettings.model_construct(db="not-an-int")
    with pytest.raises(ConfigurationError, match="db must be an integer"):
        settings.validate_mode_requirements()

    settings = RedisSettings.model_construct(replicas=["localhost:6379"])
    with pytest.raises(ConfigurationError, match="replica routing is unsupported"):
        settings.validate_mode_requirements()

    settings = RedisSettings.model_construct(read_from_replicas="yes")
    with pytest.raises(ConfigurationError, match="read_from_replicas must be"):
        settings.validate_mode_requirements()


# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------


class _UndecodableDatabaseName(str):
    """A str subclass whose ``encode`` fails like an unpaired surrogate."""

    def encode(self, *args: Any, **kwargs: Any) -> bytes:  # type: ignore[override]
        raise UnicodeEncodeError("utf-8", "x", 0, 1, "surrogates not allowed")


def test_mongodb_database_name_must_be_encodable_utf8() -> None:
    with pytest.raises(ConfigurationError, match="configuration is invalid"):
        validate_mongodb_database(_UndecodableDatabaseName("db"))


def test_mongodb_seed_host_grammar_rejections() -> None:
    with pytest.raises(ConfigurationError, match="seed"):
        _normalize_mongodb_seed_host("bad host", "replica_set_members")


def test_mongodb_uri_authority_grammar_rejections() -> None:
    with pytest.raises(ConfigurationError, match="configuration is invalid"):
        validate_mongodb_uri("mongodb://bad!host:27017/")
    with pytest.raises(ConfigurationError, match="configuration is invalid"):
        validate_mongodb_uri("mongodb+srv://bad host/")
    # Direct authority probes pin the endpoint-grammar rejections the URI-level
    # character guard would otherwise shadow.
    with pytest.raises(ConfigurationError, match="valid server endpoint"):
        _validate_mongodb_uri_authority("mongodb", "localhost:notaport")
    with pytest.raises(ConfigurationError, match="valid server endpoint"):
        _validate_mongodb_uri_authority("mongodb+srv", "bad!host")
    with pytest.raises(ConfigurationError, match="valid server endpoint"):
        # SRV discovery names must be DNS hostnames, not IP literals.
        _validate_mongodb_uri_authority("mongodb+srv", "1.2.3.4")


def test_mongodb_direct_loopback_uri_rejections() -> None:
    assert is_mongodb_direct_loopback_uri(12345) is False
    assert is_mongodb_direct_loopback_uri("mongodb://127.0.0.1:27017/#frag") is False
    assert is_mongodb_direct_loopback_uri("http://127.0.0.1:27017/") is False
    assert is_mongodb_direct_loopback_uri("mongodb://a:1,b:2/") is False
    assert (
        is_mongodb_direct_loopback_uri(
            "mongodb://127.0.0.1:27017/?directConnection=false"
        )
        is False
    )
    # urlsplit raises ValueError for the unterminated IPv6 literal; the helper
    # catches it and answers False (never an exception to callers).
    assert is_mongodb_direct_loopback_uri("mongodb://[::1:27017/") is False


def _mongodb_transport_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "mode": MongoDBMode.STANDALONE,
        "uri": "mongodb://localhost:27017/",
        "replica_set_members": [],
        "mongos_routers": [],
        "tls_enabled": False,
        "tls_allow_invalid_certificates": False,
        "username": None,
        "password": None,
        "auth_mechanism": None,
    }
    kwargs.update(overrides)
    return kwargs


def test_mongodb_transport_security_rejects_mode_and_tls_contracts() -> None:
    with pytest.raises(ConfigurationError, match="configuration is invalid"):
        validate_mongodb_transport_security(**_mongodb_transport_kwargs(mode=12345))

    with pytest.raises(ConfigurationError, match="configuration is invalid"):
        validate_mongodb_transport_security(
            **_mongodb_transport_kwargs(tls_cert_file="/tmp/client.pem")
        )

    with pytest.raises(ConfigurationError, match="configuration is invalid"):
        validate_mongodb_transport_security(
            **_mongodb_transport_kwargs(tls_allow_invalid_certificates=True)
        )


def test_mongodb_field_validators_reject_blank_credentials() -> None:
    with pytest.raises(ConfigurationError, match="username"):
        MongoDBSettings._reject_blank_username(12345)

    with pytest.raises(ConfigurationError, match="password"):
        MongoDBSettings._reject_blank_password("raw-password")  # type: ignore[arg-type]


def test_mongodb_mode_requirements_reject_mutated_inputs() -> None:
    settings = MongoDBSettings.model_construct()
    settings.mode = "not-a-mode"  # type: ignore[assignment]
    with pytest.raises(ConfigurationError, match="mode is unsupported"):
        settings._validate_mode_requirements()

    settings = MongoDBSettings.model_construct(uri=12345)
    with pytest.raises(ConfigurationError, match="URI is malformed"):
        settings._validate_mode_requirements()

    settings = MongoDBSettings.model_construct(replica_set_name=12345)
    with pytest.raises(ConfigurationError, match="replica_set_name"):
        settings._validate_mode_requirements()


def test_mongodb_pool_ordering_rejects_non_integer_sizes() -> None:
    settings = MongoDBSettings.model_construct(min_pool_size="0")
    with pytest.raises(ConfigurationError, match="min_pool_size"):
        settings._validate_pool_size_ordering()

    settings = MongoDBSettings.model_construct(max_pool_size="1")
    with pytest.raises(ConfigurationError, match="max_pool_size"):
        settings._validate_pool_size_ordering()
