from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeVar, cast

from attrs import define as _attrs_define

T = TypeVar("T", bound="PolicyActivationIn")


@_attrs_define
class PolicyActivationIn:
    """
    Attributes:
        checksum (str):
        confirm (Literal['ACTIVATE']):
    """

    checksum: str
    confirm: Literal["ACTIVATE"]

    def to_dict(self) -> dict[str, Any]:
        checksum = self.checksum

        confirm = self.confirm

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "checksum": checksum,
                "confirm": confirm,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        checksum = d.pop("checksum")

        confirm = cast(Literal["ACTIVATE"], d.pop("confirm"))
        if confirm != "ACTIVATE":
            raise ValueError(f"confirm must match const 'ACTIVATE', got '{confirm}'")

        policy_activation_in = cls(
            checksum=checksum,
            confirm=confirm,
        )

        return policy_activation_in
