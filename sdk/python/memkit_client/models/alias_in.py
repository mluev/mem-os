from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="AliasIn")


@_attrs_define
class AliasIn:
    """
    Attributes:
        alias (str):
    """

    alias: str

    def to_dict(self) -> dict[str, Any]:
        alias = self.alias

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "alias": alias,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        alias = d.pop("alias")

        alias_in = cls(
            alias=alias,
        )

        return alias_in
