from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="LoginIn")


@_attrs_define
class LoginIn:
    """
    Attributes:
        handle (str):
        password (str):
    """

    handle: str
    password: str

    def to_dict(self) -> dict[str, Any]:
        handle = self.handle

        password = self.password

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "handle": handle,
                "password": password,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        handle = d.pop("handle")

        password = d.pop("password")

        login_in = cls(
            handle=handle,
            password=password,
        )

        return login_in
