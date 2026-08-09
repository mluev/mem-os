from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="ConsolidateIn")


@_attrs_define
class ConsolidateIn:
    """
    Attributes:
        dry_run (bool | Unset):  Default: True.
    """

    dry_run: bool | Unset = True

    def to_dict(self) -> dict[str, Any]:
        dry_run = self.dry_run

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dry_run = d.pop("dry_run", UNSET)

        consolidate_in = cls(
            dry_run=dry_run,
        )

        return consolidate_in
