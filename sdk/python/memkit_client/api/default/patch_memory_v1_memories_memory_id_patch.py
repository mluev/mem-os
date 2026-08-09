from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.memory_patch import MemoryPatch
from ...models.patch_memory_v1_memories_memory_id_patch_response_patch_memory_v1_memories_memory_id_patch import (
    PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch,
)
from ...types import Response


def _get_kwargs(
    memory_id: str,
    *,
    body: MemoryPatch,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/v1/memories/{memory_id}".format(
            memory_id=quote(str(memory_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch | None:
    if response.status_code == 200:
        response_200 = PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch.from_dict(
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
) -> Response[HTTPValidationError | PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch]:
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
    body: MemoryPatch,
) -> Response[HTTPValidationError | PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch]:
    """Patch Memory

    Args:
        memory_id (str):
        body (MemoryPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch]
    """

    kwargs = _get_kwargs(
        memory_id=memory_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    memory_id: str,
    *,
    client: AuthenticatedClient,
    body: MemoryPatch,
) -> HTTPValidationError | PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch | None:
    """Patch Memory

    Args:
        memory_id (str):
        body (MemoryPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch
    """

    return sync_detailed(
        memory_id=memory_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    memory_id: str,
    *,
    client: AuthenticatedClient,
    body: MemoryPatch,
) -> Response[HTTPValidationError | PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch]:
    """Patch Memory

    Args:
        memory_id (str):
        body (MemoryPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch]
    """

    kwargs = _get_kwargs(
        memory_id=memory_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    memory_id: str,
    *,
    client: AuthenticatedClient,
    body: MemoryPatch,
) -> HTTPValidationError | PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch | None:
    """Patch Memory

    Args:
        memory_id (str):
        body (MemoryPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PatchMemoryV1MemoriesMemoryIdPatchResponsePatchMemoryV1MemoriesMemoryIdPatch
    """

    return (
        await asyncio_detailed(
            memory_id=memory_id,
            client=client,
            body=body,
        )
    ).parsed
