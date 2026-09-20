from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.scope_view_kind import ScopeViewKind

T = TypeVar("T", bound="ScopeView")


@_attrs_define
class ScopeView:
    """
    Attributes:
        id (str):
        kind (ScopeViewKind):
        name (str):
        slug (str):
        writable (bool):
    """

    id: str
    kind: ScopeViewKind
    name: str
    slug: str
    writable: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        kind = self.kind.value

        name = self.name

        slug = self.slug

        writable = self.writable

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "kind": kind,
                "name": name,
                "slug": slug,
                "writable": writable,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        kind = ScopeViewKind(d.pop("kind"))

        name = d.pop("name")

        slug = d.pop("slug")

        writable = d.pop("writable")

        scope_view = cls(
            id=id,
            kind=kind,
            name=name,
            slug=slug,
            writable=writable,
        )

        scope_view.additional_properties = d
        return scope_view

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
