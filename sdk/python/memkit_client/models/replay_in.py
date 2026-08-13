from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="ReplayIn")


@_attrs_define
class ReplayIn:
    """
    Attributes:
        apply (bool | Unset):  Default: False.
    """

    apply: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        apply = self.apply

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if apply is not UNSET:
            field_dict["apply"] = apply

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        apply = d.pop("apply", UNSET)

        replay_in = cls(
            apply=apply,
        )

        return replay_in
