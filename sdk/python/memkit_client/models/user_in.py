from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.user_in_role import UserInRole
from ..types import UNSET, Unset

T = TypeVar("T", bound="UserIn")


@_attrs_define
class UserIn:
    """
    Attributes:
        display_name (str):
        handle (str):
        password (str):
        email (None | str | Unset):
        role (UserInRole | Unset):  Default: UserInRole.MEMBER.
    """

    display_name: str
    handle: str
    password: str
    email: None | str | Unset = UNSET
    role: UserInRole | Unset = UserInRole.MEMBER

    def to_dict(self) -> dict[str, Any]:
        display_name = self.display_name

        handle = self.handle

        password = self.password

        email: None | str | Unset
        if isinstance(self.email, Unset):
            email = UNSET
        else:
            email = self.email

        role: str | Unset = UNSET
        if not isinstance(self.role, Unset):
            role = self.role.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "display_name": display_name,
                "handle": handle,
                "password": password,
            }
        )
        if email is not UNSET:
            field_dict["email"] = email
        if role is not UNSET:
            field_dict["role"] = role

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        display_name = d.pop("display_name")

        handle = d.pop("handle")

        password = d.pop("password")

        def _parse_email(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        email = _parse_email(d.pop("email", UNSET))

        _role = d.pop("role", UNSET)
        role: UserInRole | Unset
        if isinstance(_role, Unset):
            role = UNSET
        else:
            role = UserInRole(_role)

        user_in = cls(
            display_name=display_name,
            handle=handle,
            password=password,
            email=email,
            role=role,
        )

        return user_in
