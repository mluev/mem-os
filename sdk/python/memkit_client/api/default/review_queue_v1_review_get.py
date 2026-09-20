from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.review_queue_out import ReviewQueueOut
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    kind: None | str | Unset = UNSET,
    limit: int | Unset = 50,
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

    json_kind: None | str | Unset
    if isinstance(kind, Unset):
        json_kind = UNSET
    else:
        json_kind = kind
    params["kind"] = json_kind

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/review",
        "params": params,
        "cookies": cookies,
    }

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | ReviewQueueOut | None:
    if response.status_code == 200:
        response_200 = ReviewQueueOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | ReviewQueueOut]:
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
    limit: int | Unset = 50,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | ReviewQueueOut]:
    r"""Review Queue

     Everything waiting on a person.

    Four different things share one queue because they share one question --
    \"is this right?\" -- and splitting them across screens is how a queue stops
    being read. Pending memories are found by their review status rather than
    duplicated into a work table, so confirming one cannot leave a stale row.

    Args:
        kind (None | str | Unset):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ReviewQueueOut]
    """

    kwargs = _get_kwargs(
        kind=kind,
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
    *,
    client: AuthenticatedClient,
    kind: None | str | Unset = UNSET,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> HTTPValidationError | ReviewQueueOut | None:
    r"""Review Queue

     Everything waiting on a person.

    Four different things share one queue because they share one question --
    \"is this right?\" -- and splitting them across screens is how a queue stops
    being read. Pending memories are found by their review status rather than
    duplicated into a work table, so confirming one cannot leave a stale row.

    Args:
        kind (None | str | Unset):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ReviewQueueOut
    """

    return sync_detailed(
        client=client,
        kind=kind,
        limit=limit,
        offset=offset,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    kind: None | str | Unset = UNSET,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | ReviewQueueOut]:
    r"""Review Queue

     Everything waiting on a person.

    Four different things share one queue because they share one question --
    \"is this right?\" -- and splitting them across screens is how a queue stops
    being read. Pending memories are found by their review status rather than
    duplicated into a work table, so confirming one cannot leave a stale row.

    Args:
        kind (None | str | Unset):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ReviewQueueOut]
    """

    kwargs = _get_kwargs(
        kind=kind,
        limit=limit,
        offset=offset,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    kind: None | str | Unset = UNSET,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> HTTPValidationError | ReviewQueueOut | None:
    r"""Review Queue

     Everything waiting on a person.

    Four different things share one queue because they share one question --
    \"is this right?\" -- and splitting them across screens is how a queue stops
    being read. Pending memories are found by their review status rather than
    duplicated into a work table, so confirming one cannot leave a stale row.

    Args:
        kind (None | str | Unset):
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ReviewQueueOut
    """

    return (
        await asyncio_detailed(
            client=client,
            kind=kind,
            limit=limit,
            offset=offset,
            x_requested_with=x_requested_with,
            memkit_session=memkit_session,
        )
    ).parsed
