from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.linked_memory_relation import LinkedMemoryRelation

T = TypeVar("T", bound="LinkedMemory")


@_attrs_define
class LinkedMemory:
    """
    Attributes:
        document_date (None | str):
        event_dates (list[str]):
        id (str):
        kind (str):
        relation (LinkedMemoryRelation):
        source_role (str):
        status (str):
        text (str):
        valid_until (None | str):
    """

    document_date: None | str
    event_dates: list[str]
    id: str
    kind: str
    relation: LinkedMemoryRelation
    source_role: str
    status: str
    text: str
    valid_until: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        document_date: None | str
        document_date = self.document_date

        event_dates = self.event_dates

        id = self.id

        kind = self.kind

        relation = self.relation.value

        source_role = self.source_role

        status = self.status

        text = self.text

        valid_until: None | str
        valid_until = self.valid_until

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "document_date": document_date,
                "event_dates": event_dates,
                "id": id,
                "kind": kind,
                "relation": relation,
                "source_role": source_role,
                "status": status,
                "text": text,
                "valid_until": valid_until,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_document_date(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        document_date = _parse_document_date(d.pop("document_date"))

        event_dates = cast(list[str], d.pop("event_dates"))

        id = d.pop("id")

        kind = d.pop("kind")

        relation = LinkedMemoryRelation(d.pop("relation"))

        source_role = d.pop("source_role")

        status = d.pop("status")

        text = d.pop("text")

        def _parse_valid_until(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        valid_until = _parse_valid_until(d.pop("valid_until"))

        linked_memory = cls(
            document_date=document_date,
            event_dates=event_dates,
            id=id,
            kind=kind,
            relation=relation,
            source_role=source_role,
            status=status,
            text=text,
            valid_until=valid_until,
        )

        linked_memory.additional_properties = d
        return linked_memory

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()
