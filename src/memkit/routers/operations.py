from fastapi import APIRouter, FastAPI

from ._adopt import adopt as _adopt

router = APIRouter(tags=["operations"])


def adopt(app: FastAPI) -> None:
    _adopt(
        app,
        router,
        lambda path: (
            path in {"/healthz", "/readyz", "/v1/export", "/v1/erase"}
            or path.startswith(("/v1/admin", "/v1/jobs"))
        ),
    )
