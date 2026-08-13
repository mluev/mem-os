from fastapi import APIRouter, FastAPI

from ._adopt import adopt as _adopt

router = APIRouter(tags=["replay and evaluation"])


def adopt(app: FastAPI) -> None:
    _adopt(
        app,
        router,
        lambda path: (
            path.startswith(("/v1/replay-batches", "/v1/evaluations"))
            or path == "/v1/admin/reextract"
        ),
    )
