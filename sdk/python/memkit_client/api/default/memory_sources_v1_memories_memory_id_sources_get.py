from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.memory_sources_v1_memories_memory_id_sources_get_response_memory_sources_v1_memories_memory_id_sources_get import (
    MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet,
)
from ...types import Response


def _get_kwargs(
    memory_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/memories/{memory_id}/sources".format(
            memory_id=quote(str(memory_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    HTTPValidationError
    | MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet
    | None
):
    if response.status_code == 200:
        response_200 = (
            MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet.from_dict(
                response.json()
            )
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
) -> Response[
    HTTPValidationError | MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    memory_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[
    HTTPValidationError | MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet
]:
    """Memory Sources

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet]
    """

    kwargs = _get_kwargs(
        memory_id=memory_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    memory_id: str,
    *,
    client: AuthenticatedClient,
) -> (
    HTTPValidationError
    | MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet
    | None
):
    """Memory Sources

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet
    """

    return sync_detailed(
        memory_id=memory_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    memory_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[
    HTTPValidationError | MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet
]:
    """Memory Sources

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet]
    """

    kwargs = _get_kwargs(
        memory_id=memory_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    memory_id: str,
    *,
    client: AuthenticatedClient,
) -> (
    HTTPValidationError
    | MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet
    | None
):
    """Memory Sources

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemorySourcesV1MemoriesMemoryIdSourcesGetResponseMemorySourcesV1MemoriesMemoryIdSourcesGet
    """

    return (
        await asyncio_detailed(
            memory_id=memory_id,
            client=client,
        )
    ).parsed
