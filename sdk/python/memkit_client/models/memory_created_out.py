from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="MemoryCreatedOut")


@_attrs_define
class MemoryCreatedOut:
    """
    Attributes:
        id (str):
        indexed (bool):
        stored (bool):
        index_job_id (None | str | Unset):
    """

    id: str
    indexed: bool
    stored: bool
    index_job_id: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        indexed = self.indexed

        stored = self.stored

        index_job_id: None | str | Unset
        if isinstance(self.index_job_id, Unset):
            index_job_id = UNSET
        else:
            index_job_id = self.index_job_id

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "indexed": indexed,
                "stored": stored,
            }
        )
        if index_job_id is not UNSET:
            field_dict["index_job_id"] = index_job_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        indexed = d.pop("indexed")

        stored = d.pop("stored")

        def _parse_index_job_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        index_job_id = _parse_index_job_id(d.pop("index_job_id", UNSET))

        memory_created_out = cls(
            id=id,
            indexed=indexed,
            stored=stored,
            index_job_id=index_job_id,
        )

        return memory_created_out
