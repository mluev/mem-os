from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.start_reindex_v1_admin_reindex_post_response_start_reindex_v1_admin_reindex_post import (
    StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost,
)
from ...types import Response


def _get_kwargs() -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/admin/reindex",
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost | None:
    if response.status_code == 202:
        response_202 = StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost.from_dict(response.json())

        return response_202

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost]:
    """Start Reindex

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
) -> StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost | None:
    """Start Reindex

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost]:
    """Start Reindex

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
) -> StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost | None:
    """Start Reindex

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        StartReindexV1AdminReindexPostResponseStartReindexV1AdminReindexPost
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
