"""Stable project/spider identities used by durable component keys."""

from __future__ import annotations

from typing import Any

DEFAULT_PROJECT_NAME = "default"
DEFAULT_QUEUE_KEY_TEMPLATE = "scheduler-queue:{project}:{spider}"
DEFAULT_DUPEFILTER_KEY_TEMPLATE = "dupefilter:{project}:{spider}"


def project_name_from_settings(settings: Any) -> str:
    """Return the configured Scrapy project identity.

    ``BOT_NAME`` is Scrapy's canonical project identifier.  A small stable
    fallback keeps programmatic component construction deterministic when no
    crawler settings are attached.
    """
    try:
        value = settings.get("BOT_NAME")
    except (AttributeError, TypeError):
        value = None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_PROJECT_NAME


def project_name_from_spider(spider: Any) -> str:
    """Resolve a spider's project identity without requiring a crawler."""
    crawler = getattr(spider, "crawler", None)
    settings = getattr(crawler, "settings", None) if crawler is not None else None
    return project_name_from_settings(settings)


def resolve_identity_template(
    template: str,
    *,
    spider_name: str | None = None,
    project_name: str | None = None,
) -> str:
    """Substitute known identity placeholders in a backend key template.

    Identity templates delimit fields with ``:`` (``scheduler-queue:{project}:
    {spider}``), so a substituted field value that itself contains ``:``
    composes the same physical key as a different (project, spider) pair —
    silently sharing one queue or dupefilter across spiders. A value carrying
    ``:`` is therefore rejected with ``ValueError`` when its placeholder is
    substituted; a literal key without placeholders never embeds the values
    and remains the explicit escape hatch for names that must carry colons.
    """
    for field, value, placeholder in (
        ("project", project_name, "{project}"),
        ("spider", spider_name, "{spider}"),
    ):
        if value is not None and placeholder in template and ":" in value:
            raise ValueError(
                f"Identity field {field!r} must not contain ':' — ':' is the "
                "delimiter of identity key templates, and a value carrying it "
                "would make distinct (project, spider) pairs collide on one "
                "backend key."
            )
    resolved = template
    if project_name is not None:
        resolved = resolved.replace("{project}", project_name)
    if spider_name is not None:
        resolved = resolved.replace("{spider}", spider_name)
    return resolved


__all__ = [
    "DEFAULT_DUPEFILTER_KEY_TEMPLATE",
    "DEFAULT_PROJECT_NAME",
    "DEFAULT_QUEUE_KEY_TEMPLATE",
    "project_name_from_settings",
    "project_name_from_spider",
    "resolve_identity_template",
]
