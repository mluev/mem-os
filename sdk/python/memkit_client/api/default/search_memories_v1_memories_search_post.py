from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.search_in import SearchIn
from ...models.search_memories_v1_memories_search_post_response_search_memories_v1_memories_search_post import (
    SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost,
)
from ...types import Response


def _get_kwargs(
    *,
    body: SearchIn,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/memories/search",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost | None:
    if response.status_code == 200:
        response_200 = SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost.from_dict(
            response.json()
        )

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
) -> Response[HTTPValidationError | SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: SearchIn,
) -> Response[HTTPValidationError | SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost]:
    """Search Memories

    Args:
        body (SearchIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: SearchIn,
) -> HTTPValidationError | SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost | None:
    """Search Memories

    Args:
        body (SearchIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: SearchIn,
) -> Response[HTTPValidationError | SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost]:
    """Search Memories

    Args:
        body (SearchIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: SearchIn,
) -> HTTPValidationError | SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost | None:
    """Search Memories

    Args:
        body (SearchIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SearchMemoriesV1MemoriesSearchPostResponseSearchMemoriesV1MemoriesSearchPost
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
