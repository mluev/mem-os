from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.offset_page_out_items_item import OffsetPageOutItemsItem


T = TypeVar("T", bound="OffsetPageOut")


@_attrs_define
class OffsetPageOut:
    """
    Attributes:
        items (list[OffsetPageOutItemsItem]):
        limit (int):
        offset (int):
        total (int):
    """

    items: list[OffsetPageOutItemsItem]
    limit: int
    offset: int
    total: int

    def to_dict(self) -> dict[str, Any]:
        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        limit = self.limit

        offset = self.offset

        total = self.total

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "items": items,
                "limit": limit,
                "offset": offset,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.offset_page_out_items_item import OffsetPageOutItemsItem

        d = dict(src_dict)
        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = OffsetPageOutItemsItem.from_dict(items_item_data)

            items.append(items_item)

        limit = d.pop("limit")

        offset = d.pop("offset")

        total = d.pop("total")

        offset_page_out = cls(
            items=items,
            limit=limit,
            offset=offset,
            total=total,
        )

        return offset_page_out
