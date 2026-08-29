#!/usr/bin/env python3
# @author  : azwpayne(https://github.com/azwpayne)
# @name    : __init__.py
# @time    : 2026/3/23 12:59 Mon
# @blog    : https://paynewu.com/
# @mail    : paynewu0719@gmail.com

"""Observability namespace (Unit F — Tier-2).

Exports the monitor interface and its two implementations:

- :class:`Monitor` — the no-op base protocol every component accepts.
- :class:`NullMonitor` — the safe default (no crawler / no stats).
- :class:`ScrapyStatsMonitor` — emits namespaced Scrapy stats; wired by
  ``from_crawler`` factories when ``crawler.stats`` is available.

Components (``BackendQueue``, ``BackendDupeFilter``, later the pipeline)
accept a ``monitor: Monitor = NullMonitor()`` and call hooks at their seam
points. The wiring is additive — existing stat keys are unchanged.
"""

from __future__ import annotations

# P3-4 L5: the package init is the one seam for monitor consumers — every
# public name the components use is re-exported here so no consumer needs
# to reach into the private base/stats module paths.
__all__ = [
    "DEFAULT_POP_RATE_WINDOW_S",
    "Monitor",
    "NullMonitor",
    "ScrapyStatsMonitor",
]


from scrapy_extension.monitor.base import (
    DEFAULT_POP_RATE_WINDOW_S,
    Monitor,
    NullMonitor,
)
from scrapy_extension.monitor.stats import ScrapyStatsMonitor
