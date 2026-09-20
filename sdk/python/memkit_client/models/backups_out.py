from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.backup_view import BackupView


T = TypeVar("T", bound="BackupsOut")


@_attrs_define
class BackupsOut:
    """
    Attributes:
        items (list[BackupView]):
    """

    items: list[BackupView]

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
        from ..models.backup_view import BackupView

        d = dict(src_dict)
        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = BackupView.from_dict(items_item_data)

            items.append(items_item)

        backups_out = cls(
            items=items,
        )

        return backups_out
