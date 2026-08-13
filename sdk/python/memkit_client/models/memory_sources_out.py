from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.memory_sources_out_evidence_item import MemorySourcesOutEvidenceItem
    from ..models.memory_sources_out_memory import MemorySourcesOutMemory


T = TypeVar("T", bound="MemorySourcesOut")


@_attrs_define
class MemorySourcesOut:
    """
    Attributes:
        evidence (list[MemorySourcesOutEvidenceItem]):
        memory (MemorySourcesOutMemory):
        source_role (str):
    """

    evidence: list[MemorySourcesOutEvidenceItem]
    memory: MemorySourcesOutMemory
    source_role: str

    def to_dict(self) -> dict[str, Any]:
        evidence = []
        for evidence_item_data in self.evidence:
            evidence_item = evidence_item_data.to_dict()
            evidence.append(evidence_item)

        memory = self.memory.to_dict()

        source_role = self.source_role

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "evidence": evidence,
                "memory": memory,
                "source_role": source_role,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_sources_out_evidence_item import MemorySourcesOutEvidenceItem
        from ..models.memory_sources_out_memory import MemorySourcesOutMemory

        d = dict(src_dict)
        evidence = []
        _evidence = d.pop("evidence")
        for evidence_item_data in _evidence:
            evidence_item = MemorySourcesOutEvidenceItem.from_dict(evidence_item_data)

            evidence.append(evidence_item)

        memory = MemorySourcesOutMemory.from_dict(d.pop("memory"))

        source_role = d.pop("source_role")

        memory_sources_out = cls(
            evidence=evidence,
            memory=memory,
            source_role=source_role,
        )

        return memory_sources_out
