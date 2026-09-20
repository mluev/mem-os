from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.evidence_span import EvidenceSpan
    from ..models.memory_summary import MemorySummary


T = TypeVar("T", bound="MemorySourcesOut")


@_attrs_define
class MemorySourcesOut:
    """
    Attributes:
        evidence (list[EvidenceSpan]):
        memory (MemorySummary):
        source_role (str):
        historical_evidence (list[EvidenceSpan] | Unset):
    """

    evidence: list[EvidenceSpan]
    memory: MemorySummary
    source_role: str
    historical_evidence: list[EvidenceSpan] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        evidence = []
        for evidence_item_data in self.evidence:
            evidence_item = evidence_item_data.to_dict()
            evidence.append(evidence_item)

        memory = self.memory.to_dict()

        source_role = self.source_role

        historical_evidence: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.historical_evidence, Unset):
            historical_evidence = []
            for historical_evidence_item_data in self.historical_evidence:
                historical_evidence_item = historical_evidence_item_data.to_dict()
                historical_evidence.append(historical_evidence_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "evidence": evidence,
                "memory": memory,
                "source_role": source_role,
            }
        )
        if historical_evidence is not UNSET:
            field_dict["historical_evidence"] = historical_evidence

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.evidence_span import EvidenceSpan
        from ..models.memory_summary import MemorySummary

        d = dict(src_dict)
        evidence = []
        _evidence = d.pop("evidence")
        for evidence_item_data in _evidence:
            evidence_item = EvidenceSpan.from_dict(evidence_item_data)

            evidence.append(evidence_item)

        memory = MemorySummary.from_dict(d.pop("memory"))

        source_role = d.pop("source_role")

        _historical_evidence = d.pop("historical_evidence", UNSET)
        historical_evidence: list[EvidenceSpan] | Unset = UNSET
        if _historical_evidence is not UNSET:
            historical_evidence = []
            for historical_evidence_item_data in _historical_evidence:
                historical_evidence_item = EvidenceSpan.from_dict(historical_evidence_item_data)

                historical_evidence.append(historical_evidence_item)

        memory_sources_out = cls(
            evidence=evidence,
            memory=memory,
            source_role=source_role,
            historical_evidence=historical_evidence,
        )

        return memory_sources_out
