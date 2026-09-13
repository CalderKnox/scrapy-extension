# First distributed crawl

This tutorial configures a new Scrapy project to use Redis for scheduling,
duplicate filtering, and item storage. It assumes Python 3.10+, a Redis server
on `localhost:6379`, and a project created with `scrapy startproject demo .`.

## Install and start Redis

```bash
python -m pip install "scrapy-extension[redis]"
docker run --rm --name scrapy-extension-redis \
  -p 127.0.0.1:6379:6379 -d redis:7-alpine
```

The loopback bind is for development only; configure TLS and authentication for
shared or production networks.

## Enable the components

Add to `demo/settings.py`:

```python
SCHEDULER = "scrapy_extension.schedule.scheduler.BackendScheduler"
DUPEFILTER_CLASS = "scrapy_extension.dupefilter.dupefilter.BackendDupeFilter"
ITEM_PIPELINES = {"scrapy_extension.pipeline.pipeline.BackendPipeline": 300}
SCRAPY_BACKEND_TYPE = "redis"
SCRAPY_REDIS_HOST = "localhost"
SCRAPY_REDIS_PORT = 6379
SCRAPY_REDIS_NAMESPACE = "demo-dev"
```

The global backend is the fallback for all three components. Override a single
role with `SCRAPY_QUEUE_BACKEND_TYPE` (and its matching `*_SETTINGS` mapping).
Queue-only backends such as Kafka still need a Set backend for distributed
deduplication and a Storage backend for item persistence.

## Add and run a spider

Create `demo/spiders/quotes.py`:

```python
import scrapy

class QuotesSpider(scrapy.Spider):
    name = "quotes"
    start_urls = ["https://quotes.toscrape.com/"]

    def parse(self, response):
        for quote in response.css("div.quote"):
            yield {"text": quote.css("span.text::text").get(),
                   "author": quote.css("small.author::text").get()}
```

Run `scrapy crawl quotes`. Requests, fingerprints, and yielded items now use
Redis. Re-running with the same namespace demonstrates cross-process dedup;
choose a unique namespace per application and deployment.

To start over, use a new namespace or remove only `demo-dev:*` keys. Never
flush a shared Redis database. For direct backend access, use
`BackendSpiderMixin`; it does not configure Scrapy's scheduler, dupefilter, or
pipeline. See the [runnable examples](../../../examples/README.md).
