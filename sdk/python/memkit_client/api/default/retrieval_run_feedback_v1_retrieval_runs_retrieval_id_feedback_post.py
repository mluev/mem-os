from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.feedback_out import FeedbackOut
from ...models.http_validation_error import HTTPValidationError
from ...models.retrieval_run_feedback_in import RetrievalRunFeedbackIn
from ...types import UNSET, Response, Unset


def _get_kwargs(
    retrieval_id: str,
    *,
    body: RetrievalRunFeedbackIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_requested_with, Unset):
        headers["x-requested-with"] = x_requested_with

    cookies = {}
    if memkit_session is not UNSET:
        cookies["memkit_session"] = memkit_session

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/v1/retrieval-runs/{retrieval_id}/feedback".format(
            retrieval_id=quote(str(retrieval_id), safe=""),
        ),
        "cookies": cookies,
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
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[FeedbackOut | HTTPValidationError]:
    """Retrieval Run Feedback

    Args:
        retrieval_id (str):
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
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
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
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
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> FeedbackOut | HTTPValidationError | None:
    """Retrieval Run Feedback

    Args:
        retrieval_id (str):
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
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
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    ).parsed


async def asyncio_detailed(
    retrieval_id: str,
    *,
    client: AuthenticatedClient,
    body: RetrievalRunFeedbackIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> Response[FeedbackOut | HTTPValidationError]:
    """Retrieval Run Feedback

    Args:
        retrieval_id (str):
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
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
        x_requested_with=x_requested_with,
        memkit_session=memkit_session,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    retrieval_id: str,
    *,
    client: AuthenticatedClient,
    body: RetrievalRunFeedbackIn,
    x_requested_with: None | str | Unset = UNSET,
    memkit_session: None | str | Unset = UNSET,
) -> FeedbackOut | HTTPValidationError | None:
    """Retrieval Run Feedback

    Args:
        retrieval_id (str):
        x_requested_with (None | str | Unset):
        memkit_session (None | str | Unset):
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
            x_requested_with=x_requested_with,
            memkit_session=memkit_session,
        )
    ).parsed
