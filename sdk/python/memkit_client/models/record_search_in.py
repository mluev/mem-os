from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.record_search_in_filter_type_0 import RecordSearchInFilterType0


T = TypeVar("T", bound="RecordSearchIn")


@_attrs_define
class RecordSearchIn:
    """
    Attributes:
        cursor (None | str | Unset):
        filter_ (None | RecordSearchInFilterType0 | Unset):
        limit (int | Unset):  Default: 50.
    """

    cursor: None | str | Unset = UNSET
    filter_: None | RecordSearchInFilterType0 | Unset = UNSET
    limit: int | Unset = 50

    def to_dict(self) -> dict[str, Any]:
        from ..models.record_search_in_filter_type_0 import RecordSearchInFilterType0

        cursor: None | str | Unset
        if isinstance(self.cursor, Unset):
            cursor = UNSET
        else:
            cursor = self.cursor

        filter_: dict[str, Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, RecordSearchInFilterType0):
            filter_ = self.filter_.to_dict()
        else:
            filter_ = self.filter_

        limit = self.limit

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if cursor is not UNSET:
            field_dict["cursor"] = cursor
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if limit is not UNSET:
            field_dict["limit"] = limit

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.record_search_in_filter_type_0 import RecordSearchInFilterType0

        d = dict(src_dict)

        def _parse_cursor(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        cursor = _parse_cursor(d.pop("cursor", UNSET))

        def _parse_filter_(data: object) -> None | RecordSearchInFilterType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                filter_type_0 = RecordSearchInFilterType0.from_dict(data)

                return filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RecordSearchInFilterType0 | Unset, data)

        filter_ = _parse_filter_(d.pop("filter", UNSET))

        limit = d.pop("limit", UNSET)

        record_search_in = cls(
            cursor=cursor,
            filter_=filter_,
            limit=limit,
        )

        return record_search_in
