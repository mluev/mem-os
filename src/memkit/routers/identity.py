from fastapi import APIRouter, FastAPI

from ._adopt import adopt as _adopt

router = APIRouter(tags=["identity"])


def adopt(app: FastAPI) -> None:
    _adopt(
        app,
        router,
        lambda path: path.startswith(("/v1/auth", "/v1/users", "/v1/api-keys", "/v1/entities")),
    )
