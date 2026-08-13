from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="ChecksumIn")


@_attrs_define
class ChecksumIn:
    """
    Attributes:
        checksum (str):
    """

    checksum: str

    def to_dict(self) -> dict[str, Any]:
        checksum = self.checksum

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "checksum": checksum,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        checksum = d.pop("checksum")

        checksum_in = cls(
            checksum=checksum,
        )

        return checksum_in
