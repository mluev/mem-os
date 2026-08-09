from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.message_out_index_status import MessageOutIndexStatus
from ..types import UNSET, Unset

T = TypeVar("T", bound="MessageOut")


@_attrs_define
class MessageOut:
    """
    Attributes:
        index_status (MessageOutIndexStatus):
        indexed (bool):
        message_id (int):
        deduplicated (bool | Unset):  Default: False.
        extraction_job_id (None | str | Unset):
        index_job_id (None | str | Unset):
        redacted (bool | Unset):  Default: False.
        stored (bool | Unset):  Default: True.
    """

    index_status: MessageOutIndexStatus
    indexed: bool
    message_id: int
    deduplicated: bool | Unset = False
    extraction_job_id: None | str | Unset = UNSET
    index_job_id: None | str | Unset = UNSET
    redacted: bool | Unset = False
    stored: bool | Unset = True

    def to_dict(self) -> dict[str, Any]:
        index_status = self.index_status.value

        indexed = self.indexed

        message_id = self.message_id

        deduplicated = self.deduplicated

        extraction_job_id: None | str | Unset
        if isinstance(self.extraction_job_id, Unset):
            extraction_job_id = UNSET
        else:
            extraction_job_id = self.extraction_job_id

        index_job_id: None | str | Unset
        if isinstance(self.index_job_id, Unset):
            index_job_id = UNSET
        else:
            index_job_id = self.index_job_id

        redacted = self.redacted

        stored = self.stored

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "index_status": index_status,
                "indexed": indexed,
                "message_id": message_id,
            }
        )
        if deduplicated is not UNSET:
            field_dict["deduplicated"] = deduplicated
        if extraction_job_id is not UNSET:
            field_dict["extraction_job_id"] = extraction_job_id
        if index_job_id is not UNSET:
            field_dict["index_job_id"] = index_job_id
        if redacted is not UNSET:
            field_dict["redacted"] = redacted
        if stored is not UNSET:
            field_dict["stored"] = stored

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        index_status = MessageOutIndexStatus(d.pop("index_status"))

        indexed = d.pop("indexed")

        message_id = d.pop("message_id")

        deduplicated = d.pop("deduplicated", UNSET)

        def _parse_extraction_job_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        extraction_job_id = _parse_extraction_job_id(d.pop("extraction_job_id", UNSET))

        def _parse_index_job_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        index_job_id = _parse_index_job_id(d.pop("index_job_id", UNSET))

        redacted = d.pop("redacted", UNSET)

        stored = d.pop("stored", UNSET)

        message_out = cls(
            index_status=index_status,
            indexed=indexed,
            message_id=message_id,
            deduplicated=deduplicated,
            extraction_job_id=extraction_job_id,
            index_job_id=index_job_id,
            redacted=redacted,
            stored=stored,
        )

        return message_out
