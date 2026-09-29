from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="DreamIn")


@_attrs_define
class DreamIn:
    """
    Attributes:
        dry_run (bool | Unset):  Default: False.
        max_clusters (int | Unset):  Default: 8.
        scope (None | str | Unset):
    """

    dry_run: bool | Unset = False
    max_clusters: int | Unset = 8
    scope: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        dry_run = self.dry_run

        max_clusters = self.max_clusters

        scope: None | str | Unset
        if isinstance(self.scope, Unset):
            scope = UNSET
        else:
            scope = self.scope

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run
        if max_clusters is not UNSET:
            field_dict["max_clusters"] = max_clusters
        if scope is not UNSET:
            field_dict["scope"] = scope

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dry_run = d.pop("dry_run", UNSET)

        max_clusters = d.pop("max_clusters", UNSET)

        def _parse_scope(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        scope = _parse_scope(d.pop("scope", UNSET))

        dream_in = cls(
            dry_run=dry_run,
            max_clusters=max_clusters,
            scope=scope,
        )

        return dream_in
