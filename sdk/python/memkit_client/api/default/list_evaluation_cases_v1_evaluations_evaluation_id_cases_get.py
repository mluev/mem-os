from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.items_out import ItemsOut
from ...types import Response


def _get_kwargs(
    evaluation_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/evaluations/{evaluation_id}/cases".format(
            evaluation_id=quote(str(evaluation_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | ItemsOut | None:
    if response.status_code == 200:
        response_200 = ItemsOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | ItemsOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    evaluation_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | ItemsOut]:
    """List Evaluation Cases

    Args:
        evaluation_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ItemsOut]
    """

    kwargs = _get_kwargs(
        evaluation_id=evaluation_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    evaluation_id: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | ItemsOut | None:
    """List Evaluation Cases

    Args:
        evaluation_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ItemsOut
    """

    return sync_detailed(
        evaluation_id=evaluation_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    evaluation_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | ItemsOut]:
    """List Evaluation Cases

    Args:
        evaluation_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ItemsOut]
    """

    kwargs = _get_kwargs(
        evaluation_id=evaluation_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    evaluation_id: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | ItemsOut | None:
    """List Evaluation Cases

    Args:
        evaluation_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ItemsOut
    """

    return (
        await asyncio_detailed(
            evaluation_id=evaluation_id,
            client=client,
        )
    ).parsed
