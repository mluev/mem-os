"""HTTP domain routers kept separate from the stable ``memkit.api:app`` facade."""

from __future__ import annotations

from fastapi import FastAPI

from . import evidence, memory, operations, platform, replay


def mount_domain_routers(app: FastAPI) -> None:
    """Move registered v1 endpoints into explicit domain routers.

    Endpoint implementations retain one stable dependency surface while the
    runtime/OpenAPI route graph is split by bounded context. This deliberately
    runs after endpoint declaration so existing function imports and generated
    SDK operation IDs remain compatible.
    """
    for module in (evidence, memory, platform, replay, operations):
        module.adopt(app)


__all__ = ["mount_domain_routers"]
