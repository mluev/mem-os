from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.review_item import ReviewItem


T = TypeVar("T", bound="ReviewQueueOut")


@_attrs_define
class ReviewQueueOut:
    """
    Attributes:
        items (list[ReviewItem]):
    """

    items: list[ReviewItem]

    def to_dict(self) -> dict[str, Any]:
        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "items": items,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.review_item import ReviewItem

        d = dict(src_dict)
        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = ReviewItem.from_dict(items_item_data)

            items.append(items_item)

        review_queue_out = cls(
            items=items,
        )

        return review_queue_out
