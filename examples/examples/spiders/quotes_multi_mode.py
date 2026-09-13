import os

import scrapy

from examples.items import QuotesParsingMixin
from scrapy_extension import BackendSpiderMixin, BackendType

ALLOW_REMOTE_PLAINTEXT = os.environ.get(
    "SCRAPY_EXAMPLE_REDIS_ALLOW_REMOTE_PLAINTEXT", ""
).strip().lower() in {"1", "true", "yes", "on"}

SENTINEL_CONFIG = {
    "mode": "sentinel",
    # Loopback defaults keep the example valid with the local development
    # Sentinel setup.  Set the corresponding environment variables for a
    # remote deployment and enable TLS when credentials are used.
    "sentinels": os.environ.get(
        "SCRAPY_EXAMPLE_REDIS_SENTINELS", "127.0.0.1:26379"
    ).split(","),
    "sentinel_master_name": os.environ.get(
        "SCRAPY_EXAMPLE_REDIS_SENTINEL_MASTER", "mymaster"
    ),
    "sentinel_password": os.environ.get("REDIS_SENTINEL_PASSWORD") or None,
    "password": os.environ.get("REDIS_PASSWORD") or None,
    "allow_remote_plaintext": ALLOW_REMOTE_PLAINTEXT,
    "db": 0,
}

CLUSTER_CONFIG = {
    "mode": "cluster",
    "cluster_startup_nodes": os.environ.get(
        "SCRAPY_EXAMPLE_REDIS_CLUSTER_NODES", "127.0.0.1:7000"
    ).split(","),
    "password": os.environ.get("REDIS_PASSWORD") or None,
    "allow_remote_plaintext": ALLOW_REMOTE_PLAINTEXT,
    "db": 0,
    "cluster_max_redirects": 5,
}

SELECTED_CONFIG = (
  CLUSTER_CONFIG
  if os.environ.get("SCRAPY_EXAMPLE_REDIS_MODE", "sentinel").lower() == "cluster"
  else SENTINEL_CONFIG
)


class QuotesMultiModeSpider(QuotesParsingMixin, BackendSpiderMixin, scrapy.Spider):
    name = "quotes_multi_mode"
    allowed_domains = ["quotes.toscrape.com"]
    start_urls = ["https://quotes.toscrape.com"]

    backend_type = BackendType.REDIS
    backend_settings = SELECTED_CONFIG
    custom_settings = {
        "SCRAPY_BACKEND_TYPE": "redis",
        "SCRAPY_BACKEND_SETTINGS": SELECTED_CONFIG,
    }
