from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="IndexCounts")


@_attrs_define
class IndexCounts:
    """
    Attributes:
        database_active (int):
        qdrant_active (int | None):
    """

    database_active: int
    qdrant_active: int | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        database_active = self.database_active

        qdrant_active: int | None
        qdrant_active = self.qdrant_active

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "database_active": database_active,
                "qdrant_active": qdrant_active,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        database_active = d.pop("database_active")

        def _parse_qdrant_active(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        qdrant_active = _parse_qdrant_active(d.pop("qdrant_active"))

        index_counts = cls(
            database_active=database_active,
            qdrant_active=qdrant_active,
        )

        index_counts.additional_properties = d
        return index_counts

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
