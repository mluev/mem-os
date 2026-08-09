from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.create_record_v1_collections_namespace_name_records_post_response_create_record_v1_collections_namespace_name_records_post import (
    CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost,
)
from ...models.http_validation_error import HTTPValidationError
from ...models.record_in import RecordIn
from ...types import Response


def _get_kwargs(
    namespace: str,
    name: str,
    *,
    body: RecordIn,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/collections/{namespace}/{name}/records".format(
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
    CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost
    | HTTPValidationError
    | None
):
    if response.status_code == 201:
        response_201 = CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost.from_dict(
            response.json()
        )

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
) -> Response[
    CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost
    | HTTPValidationError
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
    body: RecordIn,
) -> Response[
    CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost
    | HTTPValidationError
]:
    """Create Record

    Args:
        namespace (str):
        name (str):
        body (RecordIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost | HTTPValidationError]
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
    body: RecordIn,
) -> (
    CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost
    | HTTPValidationError
    | None
):
    """Create Record

    Args:
        namespace (str):
        name (str):
        body (RecordIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost | HTTPValidationError
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
    body: RecordIn,
) -> Response[
    CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost
    | HTTPValidationError
]:
    """Create Record

    Args:
        namespace (str):
        name (str):
        body (RecordIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost | HTTPValidationError]
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
    body: RecordIn,
) -> (
    CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost
    | HTTPValidationError
    | None
):
    """Create Record

    Args:
        namespace (str):
        name (str):
        body (RecordIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateRecordV1CollectionsNamespaceNameRecordsPostResponseCreateRecordV1CollectionsNamespaceNameRecordsPost | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            namespace=namespace,
            name=name,
            client=client,
            body=body,
        )
    ).parsed
