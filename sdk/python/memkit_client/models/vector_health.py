from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="VectorHealth")


@_attrs_define
class VectorHealth:
    """
    Attributes:
        available (bool):
        error (None | str):
        memories (int | None):
        raw (int | None):
    """

    available: bool
    error: None | str
    memories: int | None
    raw: int | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        available = self.available

        error: None | str
        error = self.error

        memories: int | None
        memories = self.memories

        raw: int | None
        raw = self.raw

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "available": available,
                "error": error,
                "memories": memories,
                "raw": raw,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        available = d.pop("available")

        def _parse_error(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        error = _parse_error(d.pop("error"))

        def _parse_memories(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        memories = _parse_memories(d.pop("memories"))

        def _parse_raw(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        raw = _parse_raw(d.pop("raw"))

        vector_health = cls(
            available=available,
            error=error,
            memories=memories,
            raw=raw,
        )

        vector_health.additional_properties = d
        return vector_health

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
