from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.entity_out import EntityOut
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response


def _get_kwargs(
    namespace: str,
    name: str,
    record_id: str,
    *,
    expected_revision: int,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["expected_revision"] = expected_revision

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/v1/collections/{namespace}/{name}/records/{record_id}".format(
            namespace=quote(str(namespace), safe=""),
            name=quote(str(name), safe=""),
            record_id=quote(str(record_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EntityOut | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = EntityOut.from_dict(response.json())

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
) -> Response[EntityOut | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    namespace: str,
    name: str,
    record_id: str,
    *,
    client: AuthenticatedClient,
    expected_revision: int,
) -> Response[EntityOut | HTTPValidationError]:
    """Delete Record

    Args:
        namespace (str):
        name (str):
        record_id (str):
        expected_revision (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EntityOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        name=name,
        record_id=record_id,
        expected_revision=expected_revision,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    namespace: str,
    name: str,
    record_id: str,
    *,
    client: AuthenticatedClient,
    expected_revision: int,
) -> EntityOut | HTTPValidationError | None:
    """Delete Record

    Args:
        namespace (str):
        name (str):
        record_id (str):
        expected_revision (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EntityOut | HTTPValidationError
    """

    return sync_detailed(
        namespace=namespace,
        name=name,
        record_id=record_id,
        client=client,
        expected_revision=expected_revision,
    ).parsed


async def asyncio_detailed(
    namespace: str,
    name: str,
    record_id: str,
    *,
    client: AuthenticatedClient,
    expected_revision: int,
) -> Response[EntityOut | HTTPValidationError]:
    """Delete Record

    Args:
        namespace (str):
        name (str):
        record_id (str):
        expected_revision (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EntityOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        name=name,
        record_id=record_id,
        expected_revision=expected_revision,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    namespace: str,
    name: str,
    record_id: str,
    *,
    client: AuthenticatedClient,
    expected_revision: int,
) -> EntityOut | HTTPValidationError | None:
    """Delete Record

    Args:
        namespace (str):
        name (str):
        record_id (str):
        expected_revision (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EntityOut | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            namespace=namespace,
            name=name,
            record_id=record_id,
            client=client,
            expected_revision=expected_revision,
        )
    ).parsed
