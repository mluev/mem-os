from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeVar, cast

from attrs import define as _attrs_define

T = TypeVar("T", bound="EraseIn")


@_attrs_define
class EraseIn:
    """
    Attributes:
        confirm (Literal['ERASE ALL DATA']):
    """

    confirm: Literal["ERASE ALL DATA"]

    def to_dict(self) -> dict[str, Any]:
        confirm = self.confirm

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "confirm": confirm,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        confirm = cast(Literal["ERASE ALL DATA"], d.pop("confirm"))
        if confirm != "ERASE ALL DATA":
            raise ValueError(f"confirm must match const 'ERASE ALL DATA', got '{confirm}'")

        erase_in = cls(
            confirm=confirm,
        )

        return erase_in
