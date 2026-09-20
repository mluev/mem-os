"""HTTP domain routers kept separate from the stable ``memkit.api:app`` facade."""

from __future__ import annotations

from fastapi import FastAPI

from . import evidence, identity, memory, operations


def mount_domain_routers(app: FastAPI) -> None:
    """Move registered v1 endpoints into explicit domain routers.

    Endpoint implementations keep one dependency surface while the OpenAPI
    route graph is grouped by bounded context, which is what gives the
    generated SDKs stable, readable tags. This runs after declaration so
    function imports and operation ids stay compatible.
    """
    for module in (identity, evidence, memory, operations):
        module.adopt(app)


__all__ = ["mount_domain_routers"]
