from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.flexible_out import FlexibleOut
from ...models.http_validation_error import HTTPValidationError
from ...models.user_patch import UserPatch
from ...types import UNSET, Response, Unset


def _get_kwargs(
    user_id: str,
    *,
    body: UserPatch,
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
        "method": "patch",
        "url": "/v1/users/{user_id}".format(
            user_id=quote(str(user_id), safe=""),
        ),
        "cookies": cookies,
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> FlexibleOut | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = FlexibleOut.from_dict(response.json())

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
) -> Response[FlexibleOut | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    user_id: str,
    *,
    client: AuthenticatedClient,
    body: UserPatch,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[FlexibleOut | HTTPValidationError]:
    """Patch User

     Change a role or disable an account.

    The last enabled administrator cannot be demoted or disabled: an instance
    with no administrator cannot create users, keys, or entities again.

    Args:
        user_id (str):
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (UserPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FlexibleOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        user_id=user_id,
        body=body,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    user_id: str,
    *,
    client: AuthenticatedClient,
    body: UserPatch,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> FlexibleOut | HTTPValidationError | None:
    """Patch User

     Change a role or disable an account.

    The last enabled administrator cannot be demoted or disabled: an instance
    with no administrator cannot create users, keys, or entities again.

    Args:
        user_id (str):
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (UserPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FlexibleOut | HTTPValidationError
    """

    return sync_detailed(
        user_id=user_id,
        client=client,
        body=body,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    ).parsed


async def asyncio_detailed(
    user_id: str,
    *,
    client: AuthenticatedClient,
    body: UserPatch,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[FlexibleOut | HTTPValidationError]:
    """Patch User

     Change a role or disable an account.

    The last enabled administrator cannot be demoted or disabled: an instance
    with no administrator cannot create users, keys, or entities again.

    Args:
        user_id (str):
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (UserPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FlexibleOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        user_id=user_id,
        body=body,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    user_id: str,
    *,
    client: AuthenticatedClient,
    body: UserPatch,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> FlexibleOut | HTTPValidationError | None:
    """Patch User

     Change a role or disable an account.

    The last enabled administrator cannot be demoted or disabled: an instance
    with no administrator cannot create users, keys, or entities again.

    Args:
        user_id (str):
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (UserPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FlexibleOut | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            user_id=user_id,
            client=client,
            body=body,
            x_requested_with=x_requested_with,
            memkit_session=memkit_session,
        )
    ).parsed
