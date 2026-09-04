from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.items_out import ItemsOut
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    status: None | str | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    limit: int | Unset = 50,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_requested_with, Unset):
        headers["x-requested-with"] = x_requested_with

    cookies = {}
    if memkit_session is not UNSET:
        cookies["memkit_session"] = memkit_session

    params: dict[str, Any] = {}

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    else:
        json_status = status
    params["status"] = json_status

    json_kind: None | str | Unset
    if isinstance(kind, Unset):
        json_kind = UNSET
    else:
        json_kind = kind
    params["kind"] = json_kind

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/jobs",
        "params": params,
        "cookies": cookies,
    }

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | ItemsOut | None:
    if response.status_code == 200:
        response_200 = ItemsOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | ItemsOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    status: None | str | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    limit: int | Unset = 50,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | ItemsOut]:
    """List Jobs

    Args:
        status (None | str | Unset):
        kind (None | str | Unset):
        limit (int | Unset):  Default: 50.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ItemsOut]
    """

    kwargs = _get_kwargs(
        status=status,
        kind=kind,
        limit=limit,
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
    status: None | str | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    limit: int | Unset = 50,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> HTTPValidationError | ItemsOut | None:
    """List Jobs

    Args:
        status (None | str | Unset):
        kind (None | str | Unset):
        limit (int | Unset):  Default: 50.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ItemsOut
    """

    return sync_detailed(
        client=client,
        status=status,
        kind=kind,
        limit=limit,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    status: None | str | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    limit: int | Unset = 50,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | ItemsOut]:
    """List Jobs

    Args:
        status (None | str | Unset):
        kind (None | str | Unset):
        limit (int | Unset):  Default: 50.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ItemsOut]
    """

    kwargs = _get_kwargs(
        status=status,
        kind=kind,
        limit=limit,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    status: None | str | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    limit: int | Unset = 50,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> HTTPValidationError | ItemsOut | None:
    """List Jobs

    Args:
        status (None | str | Unset):
        kind (None | str | Unset):
        limit (int | Unset):  Default: 50.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ItemsOut
    """

    return (
        await asyncio_detailed(
            client=client,
            status=status,
            kind=kind,
            limit=limit,
            x_requested_with=x_requested_with,
            memkit_session=memkit_session,
        )
    ).parsed
