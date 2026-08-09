from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.start_replay_report_v1_admin_reextract_post_response_start_replay_report_v1_admin_reextract_post import (
    StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost,
)
from ...types import Response


def _get_kwargs() -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/admin/reextract",
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost | None:
    if response.status_code == 202:
        response_202 = StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost.from_dict(
            response.json()
        )

        return response_202

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost]:
    """Start Replay Report

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
) -> StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost | None:
    """Start Replay Report

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost]:
    """Start Replay Report

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
) -> StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost | None:
    """Start Replay Report

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        StartReplayReportV1AdminReextractPostResponseStartReplayReportV1AdminReextractPost
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
