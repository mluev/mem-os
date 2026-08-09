from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.record_history_v1_collections_namespace_name_records_record_id_history_get_response_record_history_v1_collections_namespace_name_records_record_id_history_get import (
    RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet,
)
from ...types import Response


def _get_kwargs(
    namespace: str,
    name: str,
    record_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/collections/{namespace}/{name}/records/{record_id}/history".format(
            namespace=quote(str(namespace), safe=""),
            name=quote(str(name), safe=""),
            record_id=quote(str(record_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    HTTPValidationError
    | RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet
    | None
):
    if response.status_code == 200:
        response_200 = RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet.from_dict(
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
) -> Response[
    HTTPValidationError
    | RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet
]:
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
) -> Response[
    HTTPValidationError
    | RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet
]:
    """Record History

    Args:
        namespace (str):
        name (str):
        record_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        name=name,
        record_id=record_id,
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
) -> (
    HTTPValidationError
    | RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet
    | None
):
    """Record History

    Args:
        namespace (str):
        name (str):
        record_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet
    """

    return sync_detailed(
        namespace=namespace,
        name=name,
        record_id=record_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    namespace: str,
    name: str,
    record_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[
    HTTPValidationError
    | RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet
]:
    """Record History

    Args:
        namespace (str):
        name (str):
        record_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        name=name,
        record_id=record_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    namespace: str,
    name: str,
    record_id: str,
    *,
    client: AuthenticatedClient,
) -> (
    HTTPValidationError
    | RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet
    | None
):
    """Record History

    Args:
        namespace (str):
        name (str):
        record_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | RecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGetResponseRecordHistoryV1CollectionsNamespaceNameRecordsRecordIdHistoryGet
    """

    return (
        await asyncio_detailed(
            namespace=namespace,
            name=name,
            record_id=record_id,
            client=client,
        )
    ).parsed
