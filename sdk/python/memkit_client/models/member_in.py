from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..models.member_in_role import MemberInRole
from ..types import UNSET, Unset

T = TypeVar("T", bound="MemberIn")


@_attrs_define
class MemberIn:
    """
    Attributes:
        role (MemberInRole | Unset):  Default: MemberInRole.MEMBER.
    """

    role: MemberInRole | Unset = MemberInRole.MEMBER

    def to_dict(self) -> dict[str, Any]:
        role: str | Unset = UNSET
        if not isinstance(self.role, Unset):
            role = self.role.value

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if role is not UNSET:
            field_dict["role"] = role

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        _role = d.pop("role", UNSET)
        role: MemberInRole | Unset
        if isinstance(_role, Unset):
            role = UNSET
        else:
            role = MemberInRole(_role)

        member_in = cls(
            role=role,
        )

        return member_in
