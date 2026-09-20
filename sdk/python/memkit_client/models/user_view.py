from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.user_view_role import UserViewRole

T = TypeVar("T", bound="UserView")


@_attrs_define
class UserView:
    """
    Attributes:
        created_at (None | str):
        disabled_at (None | str):
        display_name (str):
        email (None | str):
        handle (str):
        id (str):
        key_last_used_at (None | str):
        own_entity_id (None | str):
        role (UserViewRole):
    """

    created_at: None | str
    disabled_at: None | str
    display_name: str
    email: None | str
    handle: str
    id: str
    key_last_used_at: None | str
    own_entity_id: None | str
    role: UserViewRole
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at: None | str
        created_at = self.created_at

        disabled_at: None | str
        disabled_at = self.disabled_at

        display_name = self.display_name

        email: None | str
        email = self.email

        handle = self.handle

        id = self.id

        key_last_used_at: None | str
        key_last_used_at = self.key_last_used_at

        own_entity_id: None | str
        own_entity_id = self.own_entity_id

        role = self.role.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "disabled_at": disabled_at,
                "display_name": display_name,
                "email": email,
                "handle": handle,
                "id": id,
                "key_last_used_at": key_last_used_at,
                "own_entity_id": own_entity_id,
                "role": role,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        def _parse_disabled_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        disabled_at = _parse_disabled_at(d.pop("disabled_at"))

        display_name = d.pop("display_name")

        def _parse_email(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        email = _parse_email(d.pop("email"))

        handle = d.pop("handle")

        id = d.pop("id")

        def _parse_key_last_used_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        key_last_used_at = _parse_key_last_used_at(d.pop("key_last_used_at"))

        def _parse_own_entity_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        own_entity_id = _parse_own_entity_id(d.pop("own_entity_id"))

        role = UserViewRole(d.pop("role"))

        user_view = cls(
            created_at=created_at,
            disabled_at=disabled_at,
            display_name=display_name,
            email=email,
            handle=handle,
            id=id,
            key_last_used_at=key_last_used_at,
            own_entity_id=own_entity_id,
            role=role,
        )

        user_view.additional_properties = d
        return user_view

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
