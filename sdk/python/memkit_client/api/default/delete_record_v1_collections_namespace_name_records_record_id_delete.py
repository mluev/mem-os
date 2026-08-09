from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.delete_record_v1_collections_namespace_name_records_record_id_delete_response_delete_record_v1_collections_namespace_name_records_record_id_delete import (
    DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    namespace: str,
    name: str,
    record_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/v1/collections/{namespace}/{name}/records/{record_id}".format(
            namespace=quote(str(namespace), safe=""),
            name=quote(str(name), safe=""),
            record_id=quote(str(record_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete
    | HTTPValidationError
    | None
):
    if response.status_code == 200:
        response_200 = DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete.from_dict(
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
    DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete
    | HTTPValidationError
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
    DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete
    | HTTPValidationError
]:
    """Delete Record

    Args:
        namespace (str):
        name (str):
        record_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete | HTTPValidationError]
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
    DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete
    | HTTPValidationError
    | None
):
    """Delete Record

    Args:
        namespace (str):
        name (str):
        record_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete | HTTPValidationError
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
    DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete
    | HTTPValidationError
]:
    """Delete Record

    Args:
        namespace (str):
        name (str):
        record_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete | HTTPValidationError]
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
    DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete
    | HTTPValidationError
    | None
):
    """Delete Record

    Args:
        namespace (str):
        name (str):
        record_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDeleteResponseDeleteRecordV1CollectionsNamespaceNameRecordsRecordIdDelete | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            namespace=namespace,
            name=name,
            record_id=record_id,
            client=client,
        )
    ).parsed
