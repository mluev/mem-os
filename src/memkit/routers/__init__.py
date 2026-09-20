"""Explicit domain routers with stable endpoint names and SDK grouping."""

from fastapi import FastAPI

from . import evidence, identity, memory, operations


def mount_domain_routers(app: FastAPI) -> None:
    for module in (identity, evidence, memory, operations):
        app.include_router(module.router)
