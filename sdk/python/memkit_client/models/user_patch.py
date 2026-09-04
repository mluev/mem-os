from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.user_patch_role_type_0 import UserPatchRoleType0
from ..types import UNSET, Unset

T = TypeVar("T", bound="UserPatch")


@_attrs_define
class UserPatch:
    """
    Attributes:
        disabled (bool | None | Unset):
        display_name (None | str | Unset):
        role (None | Unset | UserPatchRoleType0):
    """

    disabled: bool | None | Unset = UNSET
    display_name: None | str | Unset = UNSET
    role: None | Unset | UserPatchRoleType0 = UNSET

    def to_dict(self) -> dict[str, Any]:
        disabled: bool | None | Unset
        if isinstance(self.disabled, Unset):
            disabled = UNSET
        else:
            disabled = self.disabled

        display_name: None | str | Unset
        if isinstance(self.display_name, Unset):
            display_name = UNSET
        else:
            display_name = self.display_name

        role: None | str | Unset
        if isinstance(self.role, Unset):
            role = UNSET
        elif isinstance(self.role, UserPatchRoleType0):
            role = self.role.value
        else:
            role = self.role

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if disabled is not UNSET:
            field_dict["disabled"] = disabled
        if display_name is not UNSET:
            field_dict["display_name"] = display_name
        if role is not UNSET:
            field_dict["role"] = role

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_disabled(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        disabled = _parse_disabled(d.pop("disabled", UNSET))

        def _parse_display_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        display_name = _parse_display_name(d.pop("display_name", UNSET))

        def _parse_role(data: object) -> None | Unset | UserPatchRoleType0:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                role_type_0 = UserPatchRoleType0(data)

                return role_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UserPatchRoleType0, data)

        role = _parse_role(d.pop("role", UNSET))

        user_patch = cls(
            disabled=disabled,
            display_name=display_name,
            role=role,
        )

        return user_patch
