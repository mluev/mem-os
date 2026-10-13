from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.forget_in import ForgetIn
from ...models.forget_out import ForgetOut
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: ForgetIn,
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
        "url": "/v1/memories/forget",
        "cookies": cookies,
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ForgetOut | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = ForgetOut.from_dict(response.json())

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
) -> Response[ForgetOut | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ForgetIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[ForgetOut | HTTPValidationError]:
    """Forget Memories

     Forget what matches a request, or exactly the ids given (decisions/0080).

    Only scopes the caller may write are searched. In query mode the judge
    model, when configured, keeps only candidates that are really about the
    request, choosing by number among those it was shown. Applying with the
    ids from a dry run forgets exactly what was reviewed, even if the store has
    changed since.

    Args:
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (ForgetIn): Forget matching memories: by a request searched semantically, or by ids.

            Forgetting archives: a forgotten memory leaves search and profiles, keeps
            its history and reason, and a reviewer can bring it back. A dry run is the
            default, because the match is semantic and a broad request selects more
            than intended.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ForgetOut | HTTPValidationError]
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
    body: ForgetIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> ForgetOut | HTTPValidationError | None:
    """Forget Memories

     Forget what matches a request, or exactly the ids given (decisions/0080).

    Only scopes the caller may write are searched. In query mode the judge
    model, when configured, keeps only candidates that are really about the
    request, choosing by number among those it was shown. Applying with the
    ids from a dry run forgets exactly what was reviewed, even if the store has
    changed since.

    Args:
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (ForgetIn): Forget matching memories: by a request searched semantically, or by ids.

            Forgetting archives: a forgotten memory leaves search and profiles, keeps
            its history and reason, and a reviewer can bring it back. A dry run is the
            default, because the match is semantic and a broad request selects more
            than intended.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ForgetOut | HTTPValidationError
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
    body: ForgetIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[ForgetOut | HTTPValidationError]:
    """Forget Memories

     Forget what matches a request, or exactly the ids given (decisions/0080).

    Only scopes the caller may write are searched. In query mode the judge
    model, when configured, keeps only candidates that are really about the
    request, choosing by number among those it was shown. Applying with the
    ids from a dry run forgets exactly what was reviewed, even if the store has
    changed since.

    Args:
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (ForgetIn): Forget matching memories: by a request searched semantically, or by ids.

            Forgetting archives: a forgotten memory leaves search and profiles, keeps
            its history and reason, and a reviewer can bring it back. A dry run is the
            default, because the match is semantic and a broad request selects more
            than intended.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ForgetOut | HTTPValidationError]
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
    body: ForgetIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> ForgetOut | HTTPValidationError | None:
    """Forget Memories

     Forget what matches a request, or exactly the ids given (decisions/0080).

    Only scopes the caller may write are searched. In query mode the judge
    model, when configured, keeps only candidates that are really about the
    request, choosing by number among those it was shown. Applying with the
    ids from a dry run forgets exactly what was reviewed, even if the store has
    changed since.

    Args:
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
        body (ForgetIn): Forget matching memories: by a request searched semantically, or by ids.

            Forgetting archives: a forgotten memory leaves search and profiles, keeps
            its history and reason, and a reviewer can bring it back. A dry run is the
            default, because the match is semantic and a broad request selects more
            than intended.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ForgetOut | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            x_requested_with=x_requested_with,
            memkit_session=memkit_session,
        )
    ).parsed
