from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.message_out import MessageOut


T = TypeVar("T", bound="BatchOut")


@_attrs_define
class BatchOut:
    """
    Attributes:
        count (int):
        items (list[MessageOut]):
    """

    count: int
    items: list[MessageOut]

    def to_dict(self) -> dict[str, Any]:
        count = self.count

        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "count": count,
                "items": items,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.message_out import MessageOut

        d = dict(src_dict)
        count = d.pop("count")

        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = MessageOut.from_dict(items_item_data)

            items.append(items_item)

        batch_out = cls(
            count=count,
            items=items,
        )

        return batch_out
