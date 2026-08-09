from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.list_namespaces_v1_namespaces_get_response_list_namespaces_v1_namespaces_get import (
    ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet,
)
from ...types import Response


def _get_kwargs() -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/namespaces",
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet | None:
    if response.status_code == 200:
        response_200 = ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet.from_dict(response.json())

        return response_200

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet]:
    """List Namespaces

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
) -> ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet | None:
    """List Namespaces

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet]:
    """List Namespaces

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
) -> ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet | None:
    """List Namespaces

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ListNamespacesV1NamespacesGetResponseListNamespacesV1NamespacesGet
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
