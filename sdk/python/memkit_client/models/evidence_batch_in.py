from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.message_in import MessageIn


T = TypeVar("T", bound="EvidenceBatchIn")


@_attrs_define
class EvidenceBatchIn:
    """
    Attributes:
        events (list[MessageIn]):
    """

    events: list[MessageIn]

    def to_dict(self) -> dict[str, Any]:
        events = []
        for events_item_data in self.events:
            events_item = events_item_data.to_dict()
            events.append(events_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "events": events,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.message_in import MessageIn

        d = dict(src_dict)
        events = []
        _events = d.pop("events")
        for events_item_data in _events:
            events_item = MessageIn.from_dict(events_item_data)

            events.append(events_item)

        evidence_batch_in = cls(
            events=events,
        )

        return evidence_batch_in
