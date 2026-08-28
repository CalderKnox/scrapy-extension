"""Request utility functions for scrapy-extension.

This module provides utility functions for working with Scrapy requests.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from scrapy.http import Request


@lru_cache(maxsize=1)
def _scrapy_fingerprint() -> Callable[[Request], Any]:
    """Resolve Scrapy's fingerprint function once.

    The per-call ``from scrapy.utils.request import fingerprint`` was a
    hot-path tax on every dupefilter admission (P1-6/F8a). The lookup stays
    lazy — first fingerprint — but the resolved function is cached, so the
    import machinery runs once per process instead of once per request.
    """
    from scrapy.utils.request import fingerprint

    return fingerprint


def request_fingerprint(request: Request) -> str:
    """Generate a unique fingerprint for a request.

    This is a wrapper around Scrapy's fingerprint function that returns
    a hex string representation of the fingerprint.

    Args:
        request: The Scrapy request to fingerprint.

    Returns:
        A fingerprint string in hexadecimal format.
    """
    fingerprint = _scrapy_fingerprint()(request)
    return cast(str, fingerprint.hex())
