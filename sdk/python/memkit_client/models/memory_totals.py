from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="MemoryTotals")


@_attrs_define
class MemoryTotals:
    """
    Attributes:
        about_someone (int):
        active (int):
        archived (int):
        pending (int):
        superseded (int):
    """

    about_someone: int
    active: int
    archived: int
    pending: int
    superseded: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        about_someone = self.about_someone

        active = self.active

        archived = self.archived

        pending = self.pending

        superseded = self.superseded

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "about_someone": about_someone,
                "active": active,
                "archived": archived,
                "pending": pending,
                "superseded": superseded,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        about_someone = d.pop("about_someone")

        active = d.pop("active")

        archived = d.pop("archived")

        pending = d.pop("pending")

        superseded = d.pop("superseded")

        memory_totals = cls(
            about_someone=about_someone,
            active=active,
            archived=archived,
            pending=pending,
            superseded=superseded,
        )

        memory_totals.additional_properties = d
        return memory_totals

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
