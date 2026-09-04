from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="PasswordChangeIn")


@_attrs_define
class PasswordChangeIn:
    """
    Attributes:
        current_password (str):
        new_password (str):
    """

    current_password: str
    new_password: str

    def to_dict(self) -> dict[str, Any]:
        current_password = self.current_password

        new_password = self.new_password

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "current_password": current_password,
                "new_password": new_password,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        current_password = d.pop("current_password")

        new_password = d.pop("new_password")

        password_change_in = cls(
            current_password=current_password,
            new_password=new_password,
        )

        return password_change_in
