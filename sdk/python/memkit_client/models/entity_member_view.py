from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.entity_member_view_role import EntityMemberViewRole

T = TypeVar("T", bound="EntityMemberView")


@_attrs_define
class EntityMemberView:
    """
    Attributes:
        display_name (str):
        handle (str):
        role (EntityMemberViewRole):
        user_id (str):
    """

    display_name: str
    handle: str
    role: EntityMemberViewRole
    user_id: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        display_name = self.display_name

        handle = self.handle

        role = self.role.value

        user_id = self.user_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "display_name": display_name,
                "handle": handle,
                "role": role,
                "user_id": user_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        display_name = d.pop("display_name")

        handle = d.pop("handle")

        role = EntityMemberViewRole(d.pop("role"))

        user_id = d.pop("user_id")

        entity_member_view = cls(
            display_name=display_name,
            handle=handle,
            role=role,
            user_id=user_id,
        )

        entity_member_view.additional_properties = d
        return entity_member_view

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
