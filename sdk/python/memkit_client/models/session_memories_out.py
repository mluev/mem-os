from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.memory_summary import MemorySummary
    from ..models.session_memories_out_jobs_item import SessionMemoriesOutJobsItem


T = TypeVar("T", bound="SessionMemoriesOut")


@_attrs_define
class SessionMemoriesOut:
    """
    Attributes:
        items (list[MemorySummary]):
        jobs (list[SessionMemoriesOutJobsItem]):
    """

    items: list[MemorySummary]
    jobs: list[SessionMemoriesOutJobsItem]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        jobs = []
        for jobs_item_data in self.jobs:
            jobs_item = jobs_item_data.to_dict()
            jobs.append(jobs_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "items": items,
                "jobs": jobs,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_summary import MemorySummary
        from ..models.session_memories_out_jobs_item import SessionMemoriesOutJobsItem

        d = dict(src_dict)
        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = MemorySummary.from_dict(items_item_data)

            items.append(items_item)

        jobs = []
        _jobs = d.pop("jobs")
        for jobs_item_data in _jobs:
            jobs_item = SessionMemoriesOutJobsItem.from_dict(jobs_item_data)

            jobs.append(jobs_item)

        session_memories_out = cls(
            items=items,
            jobs=jobs,
        )

        session_memories_out.additional_properties = d
        return session_memories_out

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()
