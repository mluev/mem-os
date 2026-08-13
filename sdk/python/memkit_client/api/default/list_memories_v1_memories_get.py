from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.cursor_page_out import CursorPageOut
from ...models.http_validation_error import HTTPValidationError
from ...models.list_memories_v1_memories_get_status import ListMemoriesV1MemoriesGetStatus
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    kind: None | str | Unset = UNSET,
    status: ListMemoriesV1MemoriesGetStatus | Unset = ListMemoriesV1MemoriesGetStatus.ACTIVE,
    limit: int | Unset = 100,
    cursor: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_kind: None | str | Unset
    if isinstance(kind, Unset):
        json_kind = UNSET
    else:
        json_kind = kind
    params["kind"] = json_kind

    json_status: str | Unset = UNSET
    if not isinstance(status, Unset):
        json_status = status.value

    params["status"] = json_status

    params["limit"] = limit

    json_cursor: None | str | Unset
    if isinstance(cursor, Unset):
        json_cursor = UNSET
    else:
        json_cursor = cursor
    params["cursor"] = json_cursor

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/memories",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CursorPageOut | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = CursorPageOut.from_dict(response.json())

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
) -> Response[CursorPageOut | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    kind: None | str | Unset = UNSET,
    status: ListMemoriesV1MemoriesGetStatus | Unset = ListMemoriesV1MemoriesGetStatus.ACTIVE,
    limit: int | Unset = 100,
    cursor: None | str | Unset = UNSET,
) -> Response[CursorPageOut | HTTPValidationError]:
    """List Memories

    Args:
        kind (None | str | Unset):
        status (ListMemoriesV1MemoriesGetStatus | Unset):  Default:
            ListMemoriesV1MemoriesGetStatus.ACTIVE.
        limit (int | Unset):  Default: 100.
        cursor (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CursorPageOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        kind=kind,
        status=status,
        limit=limit,
        cursor=cursor,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    kind: None | str | Unset = UNSET,
    status: ListMemoriesV1MemoriesGetStatus | Unset = ListMemoriesV1MemoriesGetStatus.ACTIVE,
    limit: int | Unset = 100,
    cursor: None | str | Unset = UNSET,
) -> CursorPageOut | HTTPValidationError | None:
    """List Memories

    Args:
        kind (None | str | Unset):
        status (ListMemoriesV1MemoriesGetStatus | Unset):  Default:
            ListMemoriesV1MemoriesGetStatus.ACTIVE.
        limit (int | Unset):  Default: 100.
        cursor (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CursorPageOut | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        kind=kind,
        status=status,
        limit=limit,
        cursor=cursor,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    kind: None | str | Unset = UNSET,
    status: ListMemoriesV1MemoriesGetStatus | Unset = ListMemoriesV1MemoriesGetStatus.ACTIVE,
    limit: int | Unset = 100,
    cursor: None | str | Unset = UNSET,
) -> Response[CursorPageOut | HTTPValidationError]:
    """List Memories

    Args:
        kind (None | str | Unset):
        status (ListMemoriesV1MemoriesGetStatus | Unset):  Default:
            ListMemoriesV1MemoriesGetStatus.ACTIVE.
        limit (int | Unset):  Default: 100.
        cursor (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CursorPageOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        kind=kind,
        status=status,
        limit=limit,
        cursor=cursor,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    kind: None | str | Unset = UNSET,
    status: ListMemoriesV1MemoriesGetStatus | Unset = ListMemoriesV1MemoriesGetStatus.ACTIVE,
    limit: int | Unset = 100,
    cursor: None | str | Unset = UNSET,
) -> CursorPageOut | HTTPValidationError | None:
    """List Memories

    Args:
        kind (None | str | Unset):
        status (ListMemoriesV1MemoriesGetStatus | Unset):  Default:
            ListMemoriesV1MemoriesGetStatus.ACTIVE.
        limit (int | Unset):  Default: 100.
        cursor (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CursorPageOut | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            kind=kind,
            status=status,
            limit=limit,
            cursor=cursor,
        )
    ).parsed
