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
        merge (bool | Unset):  Default: False.
    """

    dry_run: bool | Unset = True
    merge: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        dry_run = self.dry_run

        merge = self.merge

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run
        if merge is not UNSET:
            field_dict["merge"] = merge

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dry_run = d.pop("dry_run", UNSET)

        merge = d.pop("merge", UNSET)

        consolidate_in = cls(
            dry_run=dry_run,
            merge=merge,
        )

        return consolidate_in
