from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.session_messages_out import SessionMessagesOut
from ...types import UNSET, Response, Unset


def _get_kwargs(
    session_id: str,
    *,
    limit: int | Unset = 200,
    offset: int | Unset = 0,
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

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/admin/sessions/{session_id}/messages".format(
            session_id=quote(str(session_id), safe=""),
        ),
        "params": params,
        "cookies": cookies,
    }

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | SessionMessagesOut | None:
    if response.status_code == 200:
        response_200 = SessionMessagesOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | SessionMessagesOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    session_id: str,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 200,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | SessionMessagesOut]:
    """List Session Messages

    Args:
        session_id (str):
        limit (int | Unset):  Default: 200.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SessionMessagesOut]
    """

    kwargs = _get_kwargs(
        session_id=session_id,
        limit=limit,
        offset=offset,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    session_id: str,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 200,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> HTTPValidationError | SessionMessagesOut | None:
    """List Session Messages

    Args:
        session_id (str):
        limit (int | Unset):  Default: 200.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SessionMessagesOut
    """

    return sync_detailed(
        session_id=session_id,
        client=client,
        limit=limit,
        offset=offset,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    ).parsed


async def asyncio_detailed(
    session_id: str,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 200,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | SessionMessagesOut]:
    """List Session Messages

    Args:
        session_id (str):
        limit (int | Unset):  Default: 200.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SessionMessagesOut]
    """

    kwargs = _get_kwargs(
        session_id=session_id,
        limit=limit,
        offset=offset,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    session_id: str,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 200,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> HTTPValidationError | SessionMessagesOut | None:
    """List Session Messages

    Args:
        session_id (str):
        limit (int | Unset):  Default: 200.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SessionMessagesOut
    """

    return (
        await asyncio_detailed(
            session_id=session_id,
            client=client,
            limit=limit,
            offset=offset,
            x_requested_with=x_requested_with,
            memkit_session=memkit_session,
        )
    ).parsed
