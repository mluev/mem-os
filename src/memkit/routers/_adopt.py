from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute


def adopt(app: FastAPI, router: APIRouter, belongs: Callable[[str], bool]) -> None:
    selected = [
        route for route in app.router.routes if isinstance(route, APIRoute) and belongs(route.path)
    ]
    if not selected:
        return
    app.router.routes = [route for route in app.router.routes if route not in selected]
    router.routes.extend(selected)
    app.include_router(router)
