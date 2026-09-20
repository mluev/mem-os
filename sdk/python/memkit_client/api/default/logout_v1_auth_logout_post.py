from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.feedback_out import FeedbackOut
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    memkit_session: None | str | Unset = UNSET,
) -> dict[str, Any]:

    cookies = {}
    if memkit_session is not UNSET:
        cookies["memkit_session"] = memkit_session

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/auth/logout",
        "cookies": cookies,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> FeedbackOut | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = FeedbackOut.from_dict(response.json())

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
) -> Response[FeedbackOut | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    memkit_session: None | str | Unset = UNSET,
) -> Response[FeedbackOut | HTTPValidationError]:
    """Logout

    Args:
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FeedbackOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        memkit_session=memkit_session,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    memkit_session: None | str | Unset = UNSET,
) -> FeedbackOut | HTTPValidationError | None:
    """Logout

    Args:
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FeedbackOut | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        memkit_session=memkit_session,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    memkit_session: None | str | Unset = UNSET,
) -> Response[FeedbackOut | HTTPValidationError]:
    """Logout

    Args:
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FeedbackOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        memkit_session=memkit_session,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    memkit_session: None | str | Unset = UNSET,
) -> FeedbackOut | HTTPValidationError | None:
    """Logout

    Args:
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FeedbackOut | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            memkit_session=memkit_session,
        )
    ).parsed
