from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.export_data_v1_export_post_response_export_data_v1_export_post import (
    ExportDataV1ExportPostResponseExportDataV1ExportPost,
)
from ...types import Response


def _get_kwargs() -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/export",
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ExportDataV1ExportPostResponseExportDataV1ExportPost | None:
    if response.status_code == 202:
        response_202 = ExportDataV1ExportPostResponseExportDataV1ExportPost.from_dict(response.json())

        return response_202

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ExportDataV1ExportPostResponseExportDataV1ExportPost]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[ExportDataV1ExportPostResponseExportDataV1ExportPost]:
    """Export Data

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ExportDataV1ExportPostResponseExportDataV1ExportPost]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
) -> ExportDataV1ExportPostResponseExportDataV1ExportPost | None:
    """Export Data

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ExportDataV1ExportPostResponseExportDataV1ExportPost
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[ExportDataV1ExportPostResponseExportDataV1ExportPost]:
    """Export Data

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ExportDataV1ExportPostResponseExportDataV1ExportPost]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
) -> ExportDataV1ExportPostResponseExportDataV1ExportPost | None:
    """Export Data

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ExportDataV1ExportPostResponseExportDataV1ExportPost
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
