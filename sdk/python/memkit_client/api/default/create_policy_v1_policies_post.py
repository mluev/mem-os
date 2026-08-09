from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.create_policy_v1_policies_post_response_create_policy_v1_policies_post import (
    CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost,
)
from ...models.http_validation_error import HTTPValidationError
from ...models.policy_in import PolicyIn
from ...types import Response


def _get_kwargs(
    *,
    body: PolicyIn,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/policies",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost | HTTPValidationError | None:
    if response.status_code == 201:
        response_201 = CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost.from_dict(response.json())

        return response_201

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: PolicyIn,
) -> Response[CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost | HTTPValidationError]:
    """Create Policy

    Args:
        body (PolicyIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost | HTTPValidationError]
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
    body: PolicyIn,
) -> CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost | HTTPValidationError | None:
    """Create Policy

    Args:
        body (PolicyIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: PolicyIn,
) -> Response[CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost | HTTPValidationError]:
    """Create Policy

    Args:
        body (PolicyIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: PolicyIn,
) -> CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost | HTTPValidationError | None:
    """Create Policy

    Args:
        body (PolicyIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreatePolicyV1PoliciesPostResponseCreatePolicyV1PoliciesPost | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
