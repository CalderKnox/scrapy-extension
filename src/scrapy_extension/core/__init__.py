"""Leaf type/constant modules with no package-internal dependencies.

``core.types`` exists to break the settings<->backends import cycle
(P3-1): settings needs ``BackendType`` and the breaker ceiling, but
importing them from ``backends`` executed the backend package graph at
settings-import time. Both now live here — a dependency-free leaf — and
their former homes re-export them unchanged.
"""
