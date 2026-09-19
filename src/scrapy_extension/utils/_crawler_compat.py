"""Version-compatible reads of Scrapy ``Crawler`` late attributes.

scrapy >= 2.18 turned ``Crawler.stats`` / ``Crawler.request_fingerprinter`` /
``Crawler.engine`` / ``Crawler.extensions`` / ``Crawler.logformatter`` into
late attributes that raise :exc:`RuntimeError` when read before the crawl
starts; <= 2.17 returned ``None`` until then. Components that are legitimately
constructed before ``crawl()`` (e2e fixtures, ``from_crawler`` factory paths)
need the <= 2.17 semantics on every supported scrapy version.
"""

from __future__ import annotations

from typing import Any

_LATE_ATTR_SENTINEL = "is not set yet"


def crawler_late_attr(crawler: Any, name: str) -> Any:
    """Read a Crawler late attribute, returning ``None`` when it is unset.

    A genuine failure inside the attribute itself (e.g. a configured
    ``REQUEST_FINGERPRINTER_CLASS`` whose property raises) still propagates:
    only scrapy's own "is not set yet" sentinel is normalized to ``None``.
    Plain ``AttributeError`` (test doubles without the attribute) also
    normalizes to ``None``, matching the historical ``getattr(crawler, name,
    None)`` behavior on scrapy <= 2.17.
    """
    if crawler is None:
        return None
    try:
        return getattr(crawler, name)
    except AttributeError:
        return None
    except RuntimeError as exc:
        if _LATE_ATTR_SENTINEL not in str(exc):
            raise
        return None
