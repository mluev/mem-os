from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.memory_history_v1_memories_memory_id_history_get_response_memory_history_v1_memories_memory_id_history_get import (
    MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet,
)
from ...types import Response


def _get_kwargs(
    memory_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/memories/{memory_id}/history".format(
            memory_id=quote(str(memory_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    HTTPValidationError
    | MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet
    | None
):
    if response.status_code == 200:
        response_200 = (
            MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet.from_dict(
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
    HTTPValidationError | MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet
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
    HTTPValidationError | MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet
]:
    """Memory History

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet]
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
    | MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet
    | None
):
    """Memory History

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet
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
    HTTPValidationError | MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet
]:
    """Memory History

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet]
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
    | MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet
    | None
):
    """Memory History

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemoryHistoryV1MemoriesMemoryIdHistoryGetResponseMemoryHistoryV1MemoriesMemoryIdHistoryGet
    """

    return (
        await asyncio_detailed(
            memory_id=memory_id,
            client=client,
        )
    ).parsed
