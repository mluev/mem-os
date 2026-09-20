from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.message_view import MessageView
    from ..models.session_detail import SessionDetail


T = TypeVar("T", bound="SessionMessagesOut")


@_attrs_define
class SessionMessagesOut:
    """
    Attributes:
        items (list[MessageView]):
        limit (int):
        offset (int):
        session (SessionDetail):
        total (int):
    """

    items: list[MessageView]
    limit: int
    offset: int
    session: SessionDetail
    total: int

    def to_dict(self) -> dict[str, Any]:
        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        limit = self.limit

        offset = self.offset

        session = self.session.to_dict()

        total = self.total

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "items": items,
                "limit": limit,
                "offset": offset,
                "session": session,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.message_view import MessageView
        from ..models.session_detail import SessionDetail

        d = dict(src_dict)
        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = MessageView.from_dict(items_item_data)

            items.append(items_item)

        limit = d.pop("limit")

        offset = d.pop("offset")

        session = SessionDetail.from_dict(d.pop("session"))

        total = d.pop("total")

        session_messages_out = cls(
            items=items,
            limit=limit,
            offset=offset,
            session=session,
            total=total,
        )

        return session_messages_out
