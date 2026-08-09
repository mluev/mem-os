from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.collection_in import CollectionIn
from ...models.create_collection_v1_namespaces_namespace_collections_post_response_create_collection_v1_namespaces_namespace_collections_post import (
    CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    namespace: str,
    *,
    body: CollectionIn,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/namespaces/{namespace}/collections".format(
            namespace=quote(str(namespace), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost
    | HTTPValidationError
    | None
):
    if response.status_code == 201:
        response_201 = CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost.from_dict(
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
    CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost
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
    *,
    client: AuthenticatedClient,
    body: CollectionIn,
) -> Response[
    CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost
    | HTTPValidationError
]:
    """Create Collection

    Args:
        namespace (str):
        body (CollectionIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    namespace: str,
    *,
    client: AuthenticatedClient,
    body: CollectionIn,
) -> (
    CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost
    | HTTPValidationError
    | None
):
    """Create Collection

    Args:
        namespace (str):
        body (CollectionIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost | HTTPValidationError
    """

    return sync_detailed(
        namespace=namespace,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    namespace: str,
    *,
    client: AuthenticatedClient,
    body: CollectionIn,
) -> Response[
    CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost
    | HTTPValidationError
]:
    """Create Collection

    Args:
        namespace (str):
        body (CollectionIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    namespace: str,
    *,
    client: AuthenticatedClient,
    body: CollectionIn,
) -> (
    CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost
    | HTTPValidationError
    | None
):
    """Create Collection

    Args:
        namespace (str):
        body (CollectionIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateCollectionV1NamespacesNamespaceCollectionsPostResponseCreateCollectionV1NamespacesNamespaceCollectionsPost | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            namespace=namespace,
            client=client,
            body=body,
        )
    ).parsed
