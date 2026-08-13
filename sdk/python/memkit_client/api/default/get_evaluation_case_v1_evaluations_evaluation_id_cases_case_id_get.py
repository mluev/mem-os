from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.flexible_out import FlexibleOut
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    evaluation_id: str,
    case_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/evaluations/{evaluation_id}/cases/{case_id}".format(
            evaluation_id=quote(str(evaluation_id), safe=""),
            case_id=quote(str(case_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> FlexibleOut | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = FlexibleOut.from_dict(response.json())

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
) -> Response[FlexibleOut | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    evaluation_id: str,
    case_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[FlexibleOut | HTTPValidationError]:
    """Get Evaluation Case

    Args:
        evaluation_id (str):
        case_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FlexibleOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        evaluation_id=evaluation_id,
        case_id=case_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    evaluation_id: str,
    case_id: str,
    *,
    client: AuthenticatedClient,
) -> FlexibleOut | HTTPValidationError | None:
    """Get Evaluation Case

    Args:
        evaluation_id (str):
        case_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FlexibleOut | HTTPValidationError
    """

    return sync_detailed(
        evaluation_id=evaluation_id,
        case_id=case_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    evaluation_id: str,
    case_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[FlexibleOut | HTTPValidationError]:
    """Get Evaluation Case

    Args:
        evaluation_id (str):
        case_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FlexibleOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        evaluation_id=evaluation_id,
        case_id=case_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    evaluation_id: str,
    case_id: str,
    *,
    client: AuthenticatedClient,
) -> FlexibleOut | HTTPValidationError | None:
    """Get Evaluation Case

    Args:
        evaluation_id (str):
        case_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FlexibleOut | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            evaluation_id=evaluation_id,
            case_id=case_id,
            client=client,
        )
    ).parsed
