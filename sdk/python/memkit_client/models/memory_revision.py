from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.memory_revision_review_status import MemoryRevisionReviewStatus

if TYPE_CHECKING:
    from ..models.memory_revision_context import MemoryRevisionContext


T = TypeVar("T", bound="MemoryRevision")


@_attrs_define
class MemoryRevision:
    """
    Attributes:
        confidence (float):
        context (MemoryRevisionContext):
        created_at (None | str):
        extraction_version (str):
        importance (float):
        kind (str):
        review_status (MemoryRevisionReviewStatus):
        revision (int):
        source_role (str):
        status (str):
        tags (list[str]):
        text (str):
    """

    confidence: float
    context: MemoryRevisionContext
    created_at: None | str
    extraction_version: str
    importance: float
    kind: str
    review_status: MemoryRevisionReviewStatus
    revision: int
    source_role: str
    status: str
    tags: list[str]
    text: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        confidence = self.confidence

        context = self.context.to_dict()

        created_at: None | str
        created_at = self.created_at

        extraction_version = self.extraction_version

        importance = self.importance

        kind = self.kind

        review_status = self.review_status.value

        revision = self.revision

        source_role = self.source_role

        status = self.status

        tags = self.tags

        text = self.text

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "confidence": confidence,
                "context": context,
                "created_at": created_at,
                "extraction_version": extraction_version,
                "importance": importance,
                "kind": kind,
                "review_status": review_status,
                "revision": revision,
                "source_role": source_role,
                "status": status,
                "tags": tags,
                "text": text,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_revision_context import MemoryRevisionContext

        d = dict(src_dict)
        confidence = d.pop("confidence")

        context = MemoryRevisionContext.from_dict(d.pop("context"))

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        extraction_version = d.pop("extraction_version")

        importance = d.pop("importance")

        kind = d.pop("kind")

        review_status = MemoryRevisionReviewStatus(d.pop("review_status"))

        revision = d.pop("revision")

        source_role = d.pop("source_role")

        status = d.pop("status")

        tags = cast(list[str], d.pop("tags"))

        text = d.pop("text")

        memory_revision = cls(
            confidence=confidence,
            context=context,
            created_at=created_at,
            extraction_version=extraction_version,
            importance=importance,
            kind=kind,
            review_status=review_status,
            revision=revision,
            source_role=source_role,
            status=status,
            tags=tags,
            text=text,
        )

        memory_revision.additional_properties = d
        return memory_revision

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
