from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.list_policies_v1_policies_get_response_list_policies_v1_policies_get import (
    ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet,
)
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    namespace: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_namespace: None | str | Unset
    if isinstance(namespace, Unset):
        json_namespace = UNSET
    else:
        json_namespace = namespace
    params["namespace"] = json_namespace

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/policies",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet | None:
    if response.status_code == 200:
        response_200 = ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet.from_dict(response.json())

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
) -> Response[HTTPValidationError | ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    namespace: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet]:
    """List Policies

    Args:
        namespace (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    namespace: None | str | Unset = UNSET,
) -> HTTPValidationError | ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet | None:
    """List Policies

    Args:
        namespace (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet
    """

    return sync_detailed(
        client=client,
        namespace=namespace,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    namespace: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet]:
    """List Policies

    Args:
        namespace (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    namespace: None | str | Unset = UNSET,
) -> HTTPValidationError | ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet | None:
    """List Policies

    Args:
        namespace (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ListPoliciesV1PoliciesGetResponseListPoliciesV1PoliciesGet
    """

    return (
        await asyncio_detailed(
            client=client,
            namespace=namespace,
        )
    ).parsed
