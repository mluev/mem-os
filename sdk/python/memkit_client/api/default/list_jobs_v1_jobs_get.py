from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.list_jobs_v1_jobs_get_response_list_jobs_v1_jobs_get import ListJobsV1JobsGetResponseListJobsV1JobsGet
from ...models.list_jobs_v1_jobs_get_status_type_0 import ListJobsV1JobsGetStatusType0
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    status: ListJobsV1JobsGetStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 50,
    cursor: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    elif isinstance(status, ListJobsV1JobsGetStatusType0):
        json_status = status.value
    else:
        json_status = status
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
        "url": "/v1/jobs",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | ListJobsV1JobsGetResponseListJobsV1JobsGet | None:
    if response.status_code == 200:
        response_200 = ListJobsV1JobsGetResponseListJobsV1JobsGet.from_dict(response.json())

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
) -> Response[HTTPValidationError | ListJobsV1JobsGetResponseListJobsV1JobsGet]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    status: ListJobsV1JobsGetStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 50,
    cursor: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | ListJobsV1JobsGetResponseListJobsV1JobsGet]:
    """List Jobs

    Args:
        status (ListJobsV1JobsGetStatusType0 | None | Unset):
        limit (int | Unset):  Default: 50.
        cursor (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ListJobsV1JobsGetResponseListJobsV1JobsGet]
    """

    kwargs = _get_kwargs(
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
    status: ListJobsV1JobsGetStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 50,
    cursor: None | str | Unset = UNSET,
) -> HTTPValidationError | ListJobsV1JobsGetResponseListJobsV1JobsGet | None:
    """List Jobs

    Args:
        status (ListJobsV1JobsGetStatusType0 | None | Unset):
        limit (int | Unset):  Default: 50.
        cursor (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ListJobsV1JobsGetResponseListJobsV1JobsGet
    """

    return sync_detailed(
        client=client,
        status=status,
        limit=limit,
        cursor=cursor,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    status: ListJobsV1JobsGetStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 50,
    cursor: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | ListJobsV1JobsGetResponseListJobsV1JobsGet]:
    """List Jobs

    Args:
        status (ListJobsV1JobsGetStatusType0 | None | Unset):
        limit (int | Unset):  Default: 50.
        cursor (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ListJobsV1JobsGetResponseListJobsV1JobsGet]
    """

    kwargs = _get_kwargs(
        status=status,
        limit=limit,
        cursor=cursor,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    status: ListJobsV1JobsGetStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 50,
    cursor: None | str | Unset = UNSET,
) -> HTTPValidationError | ListJobsV1JobsGetResponseListJobsV1JobsGet | None:
    """List Jobs

    Args:
        status (ListJobsV1JobsGetStatusType0 | None | Unset):
        limit (int | Unset):  Default: 50.
        cursor (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ListJobsV1JobsGetResponseListJobsV1JobsGet
    """

    return (
        await asyncio_detailed(
            client=client,
            status=status,
            limit=limit,
            cursor=cursor,
        )
    ).parsed
