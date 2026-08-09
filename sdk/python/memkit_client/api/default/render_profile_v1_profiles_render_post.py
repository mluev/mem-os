from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.profile_in import ProfileIn
from ...models.render_profile_v1_profiles_render_post_response_render_profile_v1_profiles_render_post import (
    RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost,
)
from ...types import Response


def _get_kwargs(
    *,
    body: ProfileIn,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/profiles/render",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost | None:
    if response.status_code == 200:
        response_200 = RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost.from_dict(
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
) -> Response[HTTPValidationError | RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ProfileIn,
) -> Response[HTTPValidationError | RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost]:
    """Render Profile

    Args:
        body (ProfileIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: ProfileIn,
) -> HTTPValidationError | RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost | None:
    """Render Profile

    Args:
        body (ProfileIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ProfileIn,
) -> Response[HTTPValidationError | RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost]:
    """Render Profile

    Args:
        body (ProfileIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ProfileIn,
) -> HTTPValidationError | RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost | None:
    """Render Profile

    Args:
        body (ProfileIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | RenderProfileV1ProfilesRenderPostResponseRenderProfileV1ProfilesRenderPost
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
