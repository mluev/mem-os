from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.entity_usage_kind import EntityUsageKind

T = TypeVar("T", bound="EntityUsage")


@_attrs_define
class EntityUsage:
    """
    Attributes:
        about (int):
        in_scope (int):
        kind (EntityUsageKind):
        last_activity (None | str):
        members (int):
        name (str):
        slug (str):
    """

    about: int
    in_scope: int
    kind: EntityUsageKind
    last_activity: None | str
    members: int
    name: str
    slug: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        about = self.about

        in_scope = self.in_scope

        kind = self.kind.value

        last_activity: None | str
        last_activity = self.last_activity

        members = self.members

        name = self.name

        slug = self.slug

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "about": about,
                "in_scope": in_scope,
                "kind": kind,
                "last_activity": last_activity,
                "members": members,
                "name": name,
                "slug": slug,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        about = d.pop("about")

        in_scope = d.pop("in_scope")

        kind = EntityUsageKind(d.pop("kind"))

        def _parse_last_activity(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        last_activity = _parse_last_activity(d.pop("last_activity"))

        members = d.pop("members")

        name = d.pop("name")

        slug = d.pop("slug")

        entity_usage = cls(
            about=about,
            in_scope=in_scope,
            kind=kind,
            last_activity=last_activity,
            members=members,
            name=name,
            slug=slug,
        )

        entity_usage.additional_properties = d
        return entity_usage

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
