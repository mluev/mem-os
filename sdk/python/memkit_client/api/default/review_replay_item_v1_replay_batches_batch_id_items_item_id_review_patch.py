from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.flexible_out import FlexibleOut
from ...models.http_validation_error import HTTPValidationError
from ...models.replay_review_in import ReplayReviewIn
from ...types import Response


def _get_kwargs(
    batch_id: str,
    item_id: str,
    *,
    body: ReplayReviewIn,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/v1/replay-batches/{batch_id}/items/{item_id}/review".format(
            batch_id=quote(str(batch_id), safe=""),
            item_id=quote(str(item_id), safe=""),
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
    item_id: str,
    *,
    client: AuthenticatedClient,
    body: ReplayReviewIn,
) -> Response[FlexibleOut | HTTPValidationError]:
    """Review Replay Item

    Args:
        batch_id (str):
        item_id (str):
        body (ReplayReviewIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FlexibleOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        batch_id=batch_id,
        item_id=item_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    batch_id: str,
    item_id: str,
    *,
    client: AuthenticatedClient,
    body: ReplayReviewIn,
) -> FlexibleOut | HTTPValidationError | None:
    """Review Replay Item

    Args:
        batch_id (str):
        item_id (str):
        body (ReplayReviewIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FlexibleOut | HTTPValidationError
    """

    return sync_detailed(
        batch_id=batch_id,
        item_id=item_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    batch_id: str,
    item_id: str,
    *,
    client: AuthenticatedClient,
    body: ReplayReviewIn,
) -> Response[FlexibleOut | HTTPValidationError]:
    """Review Replay Item

    Args:
        batch_id (str):
        item_id (str):
        body (ReplayReviewIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FlexibleOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        batch_id=batch_id,
        item_id=item_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    batch_id: str,
    item_id: str,
    *,
    client: AuthenticatedClient,
    body: ReplayReviewIn,
) -> FlexibleOut | HTTPValidationError | None:
    """Review Replay Item

    Args:
        batch_id (str):
        item_id (str):
        body (ReplayReviewIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FlexibleOut | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            batch_id=batch_id,
            item_id=item_id,
            client=client,
            body=body,
        )
    ).parsed
