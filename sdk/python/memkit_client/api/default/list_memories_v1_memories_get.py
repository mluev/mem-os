import datetime
from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.offset_page_out import OffsetPageOut
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    q: None | str | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    status: str | Unset = "active",
    source_role: None | str | Unset = UNSET,
    scope: None | str | Unset = UNSET,
    subject: None | str | Unset = UNSET,
    review_status: None | str | Unset = UNSET,
    tag: None | str | Unset = UNSET,
    importance_min: float | None | Unset = UNSET,
    created_from: datetime.datetime | None | Unset = UNSET,
    created_to: datetime.datetime | None | Unset = UNSET,
    sort: str | Unset = "updated_at",
    order: str | Unset = "desc",
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

    json_q: None | str | Unset
    if isinstance(q, Unset):
        json_q = UNSET
    else:
        json_q = q
    params["q"] = json_q

    json_kind: None | str | Unset
    if isinstance(kind, Unset):
        json_kind = UNSET
    else:
        json_kind = kind
    params["kind"] = json_kind

    params["status"] = status

    json_source_role: None | str | Unset
    if isinstance(source_role, Unset):
        json_source_role = UNSET
    else:
        json_source_role = source_role
    params["source_role"] = json_source_role

    json_scope: None | str | Unset
    if isinstance(scope, Unset):
        json_scope = UNSET
    else:
        json_scope = scope
    params["scope"] = json_scope

    json_subject: None | str | Unset
    if isinstance(subject, Unset):
        json_subject = UNSET
    else:
        json_subject = subject
    params["subject"] = json_subject

    json_review_status: None | str | Unset
    if isinstance(review_status, Unset):
        json_review_status = UNSET
    else:
        json_review_status = review_status
    params["review_status"] = json_review_status

    json_tag: None | str | Unset
    if isinstance(tag, Unset):
        json_tag = UNSET
    else:
        json_tag = tag
    params["tag"] = json_tag

    json_importance_min: float | None | Unset
    if isinstance(importance_min, Unset):
        json_importance_min = UNSET
    else:
        json_importance_min = importance_min
    params["importance_min"] = json_importance_min

    json_created_from: None | str | Unset
    if isinstance(created_from, Unset):
        json_created_from = UNSET
    elif isinstance(created_from, datetime.datetime):
        json_created_from = created_from.isoformat()
    else:
        json_created_from = created_from
    params["created_from"] = json_created_from

    json_created_to: None | str | Unset
    if isinstance(created_to, Unset):
        json_created_to = UNSET
    elif isinstance(created_to, datetime.datetime):
        json_created_to = created_to.isoformat()
    else:
        json_created_to = created_to
    params["created_to"] = json_created_to

    params["sort"] = sort

    params["order"] = order

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/memories",
        "params": params,
        "cookies": cookies,
    }

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | OffsetPageOut | None:
    if response.status_code == 200:
        response_200 = OffsetPageOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | OffsetPageOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    q: None | str | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    status: str | Unset = "active",
    source_role: None | str | Unset = UNSET,
    scope: None | str | Unset = UNSET,
    subject: None | str | Unset = UNSET,
    review_status: None | str | Unset = UNSET,
    tag: None | str | Unset = UNSET,
    importance_min: float | None | Unset = UNSET,
    created_from: datetime.datetime | None | Unset = UNSET,
    created_to: datetime.datetime | None | Unset = UNSET,
    sort: str | Unset = "updated_at",
    order: str | Unset = "desc",
    limit: int | Unset = 50,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | OffsetPageOut]:
    r"""List Memories

     Filterable, sortable listing with a real total.

    Ordered by recency by default. The previous implementation paged by uuid
    while the dashboard called the result \"recent memories\", so the list was in
    an arbitrary order that looked chronological.

    Args:
        q (None | str | Unset):
        kind (None | str | Unset):
        status (str | Unset):  Default: 'active'.
        source_role (None | str | Unset):
        scope (None | str | Unset):
        subject (None | str | Unset):
        review_status (None | str | Unset):
        tag (None | str | Unset):
        importance_min (float | None | Unset):
        created_from (datetime.datetime | None | Unset):
        created_to (datetime.datetime | None | Unset):
        sort (str | Unset):  Default: 'updated_at'.
        order (str | Unset):  Default: 'desc'.
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | OffsetPageOut]
    """

    kwargs = _get_kwargs(
        q=q,
        kind=kind,
        status=status,
        source_role=source_role,
        scope=scope,
        subject=subject,
        review_status=review_status,
        tag=tag,
        importance_min=importance_min,
        created_from=created_from,
        created_to=created_to,
        sort=sort,
        order=order,
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
    q: None | str | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    status: str | Unset = "active",
    source_role: None | str | Unset = UNSET,
    scope: None | str | Unset = UNSET,
    subject: None | str | Unset = UNSET,
    review_status: None | str | Unset = UNSET,
    tag: None | str | Unset = UNSET,
    importance_min: float | None | Unset = UNSET,
    created_from: datetime.datetime | None | Unset = UNSET,
    created_to: datetime.datetime | None | Unset = UNSET,
    sort: str | Unset = "updated_at",
    order: str | Unset = "desc",
    limit: int | Unset = 50,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> HTTPValidationError | OffsetPageOut | None:
    r"""List Memories

     Filterable, sortable listing with a real total.

    Ordered by recency by default. The previous implementation paged by uuid
    while the dashboard called the result \"recent memories\", so the list was in
    an arbitrary order that looked chronological.

    Args:
        q (None | str | Unset):
        kind (None | str | Unset):
        status (str | Unset):  Default: 'active'.
        source_role (None | str | Unset):
        scope (None | str | Unset):
        subject (None | str | Unset):
        review_status (None | str | Unset):
        tag (None | str | Unset):
        importance_min (float | None | Unset):
        created_from (datetime.datetime | None | Unset):
        created_to (datetime.datetime | None | Unset):
        sort (str | Unset):  Default: 'updated_at'.
        order (str | Unset):  Default: 'desc'.
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | OffsetPageOut
    """

    return sync_detailed(
        client=client,
        q=q,
        kind=kind,
        status=status,
        source_role=source_role,
        scope=scope,
        subject=subject,
        review_status=review_status,
        tag=tag,
        importance_min=importance_min,
        created_from=created_from,
        created_to=created_to,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    q: None | str | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    status: str | Unset = "active",
    source_role: None | str | Unset = UNSET,
    scope: None | str | Unset = UNSET,
    subject: None | str | Unset = UNSET,
    review_status: None | str | Unset = UNSET,
    tag: None | str | Unset = UNSET,
    importance_min: float | None | Unset = UNSET,
    created_from: datetime.datetime | None | Unset = UNSET,
    created_to: datetime.datetime | None | Unset = UNSET,
    sort: str | Unset = "updated_at",
    order: str | Unset = "desc",
    limit: int | Unset = 50,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | OffsetPageOut]:
    r"""List Memories

     Filterable, sortable listing with a real total.

    Ordered by recency by default. The previous implementation paged by uuid
    while the dashboard called the result \"recent memories\", so the list was in
    an arbitrary order that looked chronological.

    Args:
        q (None | str | Unset):
        kind (None | str | Unset):
        status (str | Unset):  Default: 'active'.
        source_role (None | str | Unset):
        scope (None | str | Unset):
        subject (None | str | Unset):
        review_status (None | str | Unset):
        tag (None | str | Unset):
        importance_min (float | None | Unset):
        created_from (datetime.datetime | None | Unset):
        created_to (datetime.datetime | None | Unset):
        sort (str | Unset):  Default: 'updated_at'.
        order (str | Unset):  Default: 'desc'.
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | OffsetPageOut]
    """

    kwargs = _get_kwargs(
        q=q,
        kind=kind,
        status=status,
        source_role=source_role,
        scope=scope,
        subject=subject,
        review_status=review_status,
        tag=tag,
        importance_min=importance_min,
        created_from=created_from,
        created_to=created_to,
        sort=sort,
        order=order,
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
    q: None | str | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    status: str | Unset = "active",
    source_role: None | str | Unset = UNSET,
    scope: None | str | Unset = UNSET,
    subject: None | str | Unset = UNSET,
    review_status: None | str | Unset = UNSET,
    tag: None | str | Unset = UNSET,
    importance_min: float | None | Unset = UNSET,
    created_from: datetime.datetime | None | Unset = UNSET,
    created_to: datetime.datetime | None | Unset = UNSET,
    sort: str | Unset = "updated_at",
    order: str | Unset = "desc",
    limit: int | Unset = 50,
    offset: int | Unset = 0,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> HTTPValidationError | OffsetPageOut | None:
    r"""List Memories

     Filterable, sortable listing with a real total.

    Ordered by recency by default. The previous implementation paged by uuid
    while the dashboard called the result \"recent memories\", so the list was in
    an arbitrary order that looked chronological.

    Args:
        q (None | str | Unset):
        kind (None | str | Unset):
        status (str | Unset):  Default: 'active'.
        source_role (None | str | Unset):
        scope (None | str | Unset):
        subject (None | str | Unset):
        review_status (None | str | Unset):
        tag (None | str | Unset):
        importance_min (float | None | Unset):
        created_from (datetime.datetime | None | Unset):
        created_to (datetime.datetime | None | Unset):
        sort (str | Unset):  Default: 'updated_at'.
        order (str | Unset):  Default: 'desc'.
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | OffsetPageOut
    """

    return (
        await asyncio_detailed(
            client=client,
            q=q,
            kind=kind,
            status=status,
            source_role=source_role,
            scope=scope,
            subject=subject,
            review_status=review_status,
            tag=tag,
            importance_min=importance_min,
            created_from=created_from,
            created_to=created_to,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
            x_requested_with=x_requested_with,
            memkit_session=memkit_session,
        )
    ).parsed
