from fastapi import APIRouter, FastAPI

from ._adopt import adopt as _adopt

router = APIRouter(tags=["evidence"])


def adopt(app: FastAPI) -> None:
    _adopt(
        app,
        router,
        lambda path: path.startswith(("/v1/evidence", "/v1/messages", "/v1/sessions")),
    )
