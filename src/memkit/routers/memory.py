from fastapi import APIRouter, FastAPI

from ._adopt import adopt as _adopt

router = APIRouter(tags=["memory"])


def adopt(app: FastAPI) -> None:
    _adopt(
        app,
        router,
        lambda path: path.startswith(
            (
                "/v1/memories",
                "/v1/search",
                "/v1/retrieval",
                "/v1/profiles",
                "/v1/review",
                "/v1/attention",
            )
        ),
    )
