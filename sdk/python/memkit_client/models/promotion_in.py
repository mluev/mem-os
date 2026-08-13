from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeVar, cast

from attrs import define as _attrs_define

T = TypeVar("T", bound="PromotionIn")


@_attrs_define
class PromotionIn:
    """
    Attributes:
        checksum (str):
        confirm (Literal['PROMOTE']):
    """

    checksum: str
    confirm: Literal["PROMOTE"]

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

        confirm = cast(Literal["PROMOTE"], d.pop("confirm"))
        if confirm != "PROMOTE":
            raise ValueError(f"confirm must match const 'PROMOTE', got '{confirm}'")

        promotion_in = cls(
            checksum=checksum,
            confirm=confirm,
        )

        return promotion_in
