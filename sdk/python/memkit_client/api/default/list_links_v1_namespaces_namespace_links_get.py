from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.list_links_v1_namespaces_namespace_links_get_response_list_links_v1_namespaces_namespace_links_get import (
    ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet,
)
from ...types import Response


def _get_kwargs(
    namespace: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/namespaces/{namespace}/links".format(
            namespace=quote(str(namespace), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet | None:
    if response.status_code == 200:
        response_200 = ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet.from_dict(
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
    HTTPValidationError | ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet
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
) -> Response[
    HTTPValidationError | ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet
]:
    """List Links

    Args:
        namespace (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    namespace: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet | None:
    """List Links

    Args:
        namespace (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet
    """

    return sync_detailed(
        namespace=namespace,
        client=client,
    ).parsed


async def asyncio_detailed(
    namespace: str,
    *,
    client: AuthenticatedClient,
) -> Response[
    HTTPValidationError | ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet
]:
    """List Links

    Args:
        namespace (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    namespace: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet | None:
    """List Links

    Args:
        namespace (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ListLinksV1NamespacesNamespaceLinksGetResponseListLinksV1NamespacesNamespaceLinksGet
    """

    return (
        await asyncio_detailed(
            namespace=namespace,
            client=client,
        )
    ).parsed
