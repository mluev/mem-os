from fastapi import APIRouter, FastAPI

from ._adopt import adopt as _adopt

router = APIRouter(tags=["platform"])


def adopt(app: FastAPI) -> None:
    _adopt(
        app,
        router,
        lambda path: path.startswith(("/v1/namespaces", "/v1/collections", "/v1/policies")),
    )
