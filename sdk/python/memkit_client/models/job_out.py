from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.job_out_history_item import JobOutHistoryItem


T = TypeVar("T", bound="JobOut")


@_attrs_define
class JobOut:
    """
    Attributes:
        history (list[JobOutHistoryItem]):
        id (str):
        kind (str):
        status (str):
    """

    history: list[JobOutHistoryItem]
    id: str
    kind: str
    status: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        history = []
        for history_item_data in self.history:
            history_item = history_item_data.to_dict()
            history.append(history_item)

        id = self.id

        kind = self.kind

        status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "history": history,
                "id": id,
                "kind": kind,
                "status": status,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.job_out_history_item import JobOutHistoryItem

        d = dict(src_dict)
        history = []
        _history = d.pop("history")
        for history_item_data in _history:
            history_item = JobOutHistoryItem.from_dict(history_item_data)

            history.append(history_item)

        id = d.pop("id")

        kind = d.pop("kind")

        status = d.pop("status")

        job_out = cls(
            history=history,
            id=id,
            kind=kind,
            status=status,
        )

        job_out.additional_properties = d
        return job_out

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
