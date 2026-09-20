from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.memory_created_out import MemoryCreatedOut
from ...models.memory_in import MemoryIn
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: MemoryIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_requested_with, Unset):
        headers["x-requested-with"] = x_requested_with

    cookies = {}
    if memkit_session is not UNSET:
        cookies["memkit_session"] = memkit_session

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/memories",
        "cookies": cookies,
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | MemoryCreatedOut | None:
    if response.status_code == 201:
        response_201 = MemoryCreatedOut.from_dict(response.json())

        return response_201

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | MemoryCreatedOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: MemoryIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | MemoryCreatedOut]:
    """Post Memory

     Save one memory.

    A user's own manual save into their own scope is confirmed immediately:
    they just said it, so asking them to confirm it again is noise. Anything
    else -- a shared scope, or a model-authored write -- starts pending.

    Args:
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (MemoryIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemoryCreatedOut]
    """

    kwargs = _get_kwargs(
        body=body,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: MemoryIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> HTTPValidationError | MemoryCreatedOut | None:
    """Post Memory

     Save one memory.

    A user's own manual save into their own scope is confirmed immediately:
    they just said it, so asking them to confirm it again is noise. Anything
    else -- a shared scope, or a model-authored write -- starts pending.

    Args:
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (MemoryIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemoryCreatedOut
    """

    return sync_detailed(
        client=client,
        body=body,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: MemoryIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | MemoryCreatedOut]:
    """Post Memory

     Save one memory.

    A user's own manual save into their own scope is confirmed immediately:
    they just said it, so asking them to confirm it again is noise. Anything
    else -- a shared scope, or a model-authored write -- starts pending.

    Args:
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (MemoryIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | MemoryCreatedOut]
    """

    kwargs = _get_kwargs(
        body=body,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: MemoryIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> HTTPValidationError | MemoryCreatedOut | None:
    """Post Memory

     Save one memory.

    A user's own manual save into their own scope is confirmed immediately:
    they just said it, so asking them to confirm it again is noise. Anything
    else -- a shared scope, or a model-authored write -- starts pending.

    Args:
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (MemoryIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | MemoryCreatedOut
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            x_requested_with=x_requested_with,
            memkit_session=memkit_session,
        )
    ).parsed
