from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.memory_out import MemoryOut
from ...types import Response


def _get_kwargs(
    memory_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/memories/{memory_id}".format(
            memory_id=quote(str(memory_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | MemoryOut | None:
    if response.status_code == 200:
        response_200 = MemoryOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | MemoryOut]:
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
) -> Response[HTTPValidationError | MemoryOut]:
    """Get Memory

     One memory, including `revision`.

    A correction is a PATCH carrying `expected_revision`, so an agent needs a
    way to read the current revision of a single fact. Search results carry it
    too, but an id learned from a profile block or an earlier turn has nowhere
    else to come from.

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemoryOut]
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
) -> HTTPValidationError | MemoryOut | None:
    """Get Memory

     One memory, including `revision`.

    A correction is a PATCH carrying `expected_revision`, so an agent needs a
    way to read the current revision of a single fact. Search results carry it
    too, but an id learned from a profile block or an earlier turn has nowhere
    else to come from.

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemoryOut
    """

    return sync_detailed(
        memory_id=memory_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    memory_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | MemoryOut]:
    """Get Memory

     One memory, including `revision`.

    A correction is a PATCH carrying `expected_revision`, so an agent needs a
    way to read the current revision of a single fact. Search results carry it
    too, but an id learned from a profile block or an earlier turn has nowhere
    else to come from.

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemoryOut]
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
) -> HTTPValidationError | MemoryOut | None:
    """Get Memory

     One memory, including `revision`.

    A correction is a PATCH carrying `expected_revision`, so an agent needs a
    way to read the current revision of a single fact. Search results carry it
    too, but an id learned from a profile block or an earlier turn has nowhere
    else to come from.

    Args:
        memory_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemoryOut
    """

    return (
        await asyncio_detailed(
            memory_id=memory_id,
            client=client,
        )
    ).parsed
