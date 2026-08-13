from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.feedback_out import FeedbackOut
from ...models.http_validation_error import HTTPValidationError
from ...models.retrieval_run_feedback_in import RetrievalRunFeedbackIn
from ...types import Response


def _get_kwargs(
    retrieval_id: str,
    *,
    body: RetrievalRunFeedbackIn,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/retrieval-runs/{retrieval_id}/feedback".format(
            retrieval_id=quote(str(retrieval_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> FeedbackOut | HTTPValidationError | None:
    if response.status_code == 201:
        response_201 = FeedbackOut.from_dict(response.json())

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
) -> Response[FeedbackOut | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    retrieval_id: str,
    *,
    client: AuthenticatedClient,
    body: RetrievalRunFeedbackIn,
) -> Response[FeedbackOut | HTTPValidationError]:
    """Retrieval Run Feedback

    Args:
        retrieval_id (str):
        body (RetrievalRunFeedbackIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FeedbackOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        retrieval_id=retrieval_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    retrieval_id: str,
    *,
    client: AuthenticatedClient,
    body: RetrievalRunFeedbackIn,
) -> FeedbackOut | HTTPValidationError | None:
    """Retrieval Run Feedback

    Args:
        retrieval_id (str):
        body (RetrievalRunFeedbackIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FeedbackOut | HTTPValidationError
    """

    return sync_detailed(
        retrieval_id=retrieval_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    retrieval_id: str,
    *,
    client: AuthenticatedClient,
    body: RetrievalRunFeedbackIn,
) -> Response[FeedbackOut | HTTPValidationError]:
    """Retrieval Run Feedback

    Args:
        retrieval_id (str):
        body (RetrievalRunFeedbackIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FeedbackOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        retrieval_id=retrieval_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    retrieval_id: str,
    *,
    client: AuthenticatedClient,
    body: RetrievalRunFeedbackIn,
) -> FeedbackOut | HTTPValidationError | None:
    """Retrieval Run Feedback

    Args:
        retrieval_id (str):
        body (RetrievalRunFeedbackIn):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FeedbackOut | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            retrieval_id=retrieval_id,
            client=client,
            body=body,
        )
    ).parsed
