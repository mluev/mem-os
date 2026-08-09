from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.get_collection_v1_collections_namespace_name_get_response_get_collection_v1_collections_namespace_name_get import (
    GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    namespace: str,
    name: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/collections/{namespace}/{name}".format(
            namespace=quote(str(namespace), safe=""),
            name=quote(str(name), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet
    | HTTPValidationError
    | None
):
    if response.status_code == 200:
        response_200 = (
            GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet.from_dict(
                response.json()
            )
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
    GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet | HTTPValidationError
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
) -> Response[
    GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet | HTTPValidationError
]:
    """Get Collection

    Args:
        namespace (str):
        name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        name=name,
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
) -> (
    GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet
    | HTTPValidationError
    | None
):
    """Get Collection

    Args:
        namespace (str):
        name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet | HTTPValidationError
    """

    return sync_detailed(
        namespace=namespace,
        name=name,
        client=client,
    ).parsed


async def asyncio_detailed(
    namespace: str,
    name: str,
    *,
    client: AuthenticatedClient,
) -> Response[
    GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet | HTTPValidationError
]:
    """Get Collection

    Args:
        namespace (str):
        name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        name=name,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    namespace: str,
    name: str,
    *,
    client: AuthenticatedClient,
) -> (
    GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet
    | HTTPValidationError
    | None
):
    """Get Collection

    Args:
        namespace (str):
        name (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GetCollectionV1CollectionsNamespaceNameGetResponseGetCollectionV1CollectionsNamespaceNameGet | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            namespace=namespace,
            name=name,
            client=client,
        )
    ).parsed
