from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.memory_revision import MemoryRevision
    from ..models.memory_summary import MemorySummary


T = TypeVar("T", bound="MemoryHistoryOut")


@_attrs_define
class MemoryHistoryOut:
    """
    Attributes:
        memory (MemorySummary):
        predecessors (list[MemorySummary]):
        revisions (list[MemoryRevision]):
        successor (MemorySummary | None):
    """

    memory: MemorySummary
    predecessors: list[MemorySummary]
    revisions: list[MemoryRevision]
    successor: MemorySummary | None

    def to_dict(self) -> dict[str, Any]:
        from ..models.memory_summary import MemorySummary

        memory = self.memory.to_dict()

        predecessors = []
        for predecessors_item_data in self.predecessors:
            predecessors_item = predecessors_item_data.to_dict()
            predecessors.append(predecessors_item)

        revisions = []
        for revisions_item_data in self.revisions:
            revisions_item = revisions_item_data.to_dict()
            revisions.append(revisions_item)

        successor: dict[str, Any] | None
        if isinstance(self.successor, MemorySummary):
            successor = self.successor.to_dict()
        else:
            successor = self.successor

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "memory": memory,
                "predecessors": predecessors,
                "revisions": revisions,
                "successor": successor,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_revision import MemoryRevision
        from ..models.memory_summary import MemorySummary

        d = dict(src_dict)
        memory = MemorySummary.from_dict(d.pop("memory"))

        predecessors = []
        _predecessors = d.pop("predecessors")
        for predecessors_item_data in _predecessors:
            predecessors_item = MemorySummary.from_dict(predecessors_item_data)

            predecessors.append(predecessors_item)

        revisions = []
        _revisions = d.pop("revisions")
        for revisions_item_data in _revisions:
            revisions_item = MemoryRevision.from_dict(revisions_item_data)

            revisions.append(revisions_item)

        def _parse_successor(data: object) -> MemorySummary | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                successor_type_0 = MemorySummary.from_dict(data)

                return successor_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MemorySummary | None, data)

        successor = _parse_successor(d.pop("successor"))

        memory_history_out = cls(
            memory=memory,
            predecessors=predecessors,
            revisions=revisions,
            successor=successor,
        )

        return memory_history_out
