from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.record_search_in import RecordSearchIn
from ...models.search_records_v1_collections_namespace_name_search_post_response_search_records_v1_collections_namespace_name_search_post import (
    SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost,
)
from ...types import Response


def _get_kwargs(
    namespace: str,
    name: str,
    *,
    body: RecordSearchIn,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/collections/{namespace}/{name}/search".format(
            namespace=quote(str(namespace), safe=""),
            name=quote(str(name), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    HTTPValidationError
    | SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost
    | None
):
    if response.status_code == 200:
        response_200 = SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost.from_dict(
            response.json()
        )

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
) -> Response[
    HTTPValidationError
    | SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    namespace: str,
    name: str,
    *,
    client: AuthenticatedClient,
    body: RecordSearchIn,
) -> Response[
    HTTPValidationError
    | SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost
]:
    """Search Records

    Args:
        namespace (str):
        name (str):
        body (RecordSearchIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        name=name,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    namespace: str,
    name: str,
    *,
    client: AuthenticatedClient,
    body: RecordSearchIn,
) -> (
    HTTPValidationError
    | SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost
    | None
):
    """Search Records

    Args:
        namespace (str):
        name (str):
        body (RecordSearchIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost
    """

    return sync_detailed(
        namespace=namespace,
        name=name,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    namespace: str,
    name: str,
    *,
    client: AuthenticatedClient,
    body: RecordSearchIn,
) -> Response[
    HTTPValidationError
    | SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost
]:
    """Search Records

    Args:
        namespace (str):
        name (str):
        body (RecordSearchIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        name=name,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    namespace: str,
    name: str,
    *,
    client: AuthenticatedClient,
    body: RecordSearchIn,
) -> (
    HTTPValidationError
    | SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost
    | None
):
    """Search Records

    Args:
        namespace (str):
        name (str):
        body (RecordSearchIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SearchRecordsV1CollectionsNamespaceNameSearchPostResponseSearchRecordsV1CollectionsNamespaceNameSearchPost
    """

    return (
        await asyncio_detailed(
            namespace=namespace,
            name=name,
            client=client,
            body=body,
        )
    ).parsed
