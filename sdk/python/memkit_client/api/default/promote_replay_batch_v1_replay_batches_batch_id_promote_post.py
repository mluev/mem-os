from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.flexible_out import FlexibleOut
from ...models.http_validation_error import HTTPValidationError
from ...models.promotion_in import PromotionIn
from ...types import Response


def _get_kwargs(
    batch_id: str,
    *,
    body: PromotionIn,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/replay-batches/{batch_id}/promote".format(
            batch_id=quote(str(batch_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> FlexibleOut | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = FlexibleOut.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[FlexibleOut | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    batch_id: str,
    *,
    client: AuthenticatedClient,
    body: PromotionIn,
) -> Response[FlexibleOut | HTTPValidationError]:
    """Promote Replay Batch

    Args:
        batch_id (str):
        body (PromotionIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FlexibleOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        batch_id=batch_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    batch_id: str,
    *,
    client: AuthenticatedClient,
    body: PromotionIn,
) -> FlexibleOut | HTTPValidationError | None:
    """Promote Replay Batch

    Args:
        batch_id (str):
        body (PromotionIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FlexibleOut | HTTPValidationError
    """

    return sync_detailed(
        batch_id=batch_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    batch_id: str,
    *,
    client: AuthenticatedClient,
    body: PromotionIn,
) -> Response[FlexibleOut | HTTPValidationError]:
    """Promote Replay Batch

    Args:
        batch_id (str):
        body (PromotionIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FlexibleOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        batch_id=batch_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    batch_id: str,
    *,
    client: AuthenticatedClient,
    body: PromotionIn,
) -> FlexibleOut | HTTPValidationError | None:
    """Promote Replay Batch

    Args:
        batch_id (str):
        body (PromotionIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FlexibleOut | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            batch_id=batch_id,
            client=client,
            body=body,
        )
    ).parsed
