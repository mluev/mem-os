from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.record_patch import RecordPatch
from ...models.update_record_v1_collections_namespace_name_records_record_id_patch_response_update_record_v1_collections_namespace_name_records_record_id_patch import (
    UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch,
)
from ...types import Response


def _get_kwargs(
    namespace: str,
    name: str,
    record_id: str,
    *,
    body: RecordPatch,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/v1/collections/{namespace}/{name}/records/{record_id}".format(
            namespace=quote(str(namespace), safe=""),
            name=quote(str(name), safe=""),
            record_id=quote(str(record_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    HTTPValidationError
    | UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch
    | None
):
    if response.status_code == 200:
        response_200 = UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch.from_dict(
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
    | UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch
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
    body: RecordPatch,
) -> Response[
    HTTPValidationError
    | UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch
]:
    """Update Record

    Args:
        namespace (str):
        name (str):
        record_id (str):
        body (RecordPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        name=name,
        record_id=record_id,
        body=body,
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
    body: RecordPatch,
) -> (
    HTTPValidationError
    | UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch
    | None
):
    """Update Record

    Args:
        namespace (str):
        name (str):
        record_id (str):
        body (RecordPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch
    """

    return sync_detailed(
        namespace=namespace,
        name=name,
        record_id=record_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    namespace: str,
    name: str,
    record_id: str,
    *,
    client: AuthenticatedClient,
    body: RecordPatch,
) -> Response[
    HTTPValidationError
    | UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch
]:
    """Update Record

    Args:
        namespace (str):
        name (str):
        record_id (str):
        body (RecordPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch]
    """

    kwargs = _get_kwargs(
        namespace=namespace,
        name=name,
        record_id=record_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    namespace: str,
    name: str,
    record_id: str,
    *,
    client: AuthenticatedClient,
    body: RecordPatch,
) -> (
    HTTPValidationError
    | UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch
    | None
):
    """Update Record

    Args:
        namespace (str):
        name (str):
        record_id (str):
        body (RecordPatch):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | UpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatchResponseUpdateRecordV1CollectionsNamespaceNameRecordsRecordIdPatch
    """

    return (
        await asyncio_detailed(
            namespace=namespace,
            name=name,
            record_id=record_id,
            client=client,
            body=body,
        )
    ).parsed
