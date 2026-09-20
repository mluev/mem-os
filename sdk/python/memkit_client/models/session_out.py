from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.principal_view import PrincipalView


T = TypeVar("T", bound="SessionOut")


@_attrs_define
class SessionOut:
    """
    Attributes:
        user (PrincipalView):
        csrf_required_header (str | Unset):  Default: 'X-Requested-With'.
    """

    user: PrincipalView
    csrf_required_header: str | Unset = "X-Requested-With"

    def to_dict(self) -> dict[str, Any]:
        user = self.user.to_dict()

        csrf_required_header = self.csrf_required_header

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "user": user,
            }
        )
        if csrf_required_header is not UNSET:
            field_dict["csrf_required_header"] = csrf_required_header

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.principal_view import PrincipalView

        d = dict(src_dict)
        user = PrincipalView.from_dict(d.pop("user"))

        csrf_required_header = d.pop("csrf_required_header", UNSET)

        session_out = cls(
            user=user,
            csrf_required_header=csrf_required_header,
        )

        return session_out
