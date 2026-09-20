from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.memory_summary_review_status import MemorySummaryReviewStatus
from ..models.memory_summary_source_role import MemorySummarySourceRole
from ..models.memory_summary_status import MemorySummaryStatus

T = TypeVar("T", bound="MemorySummary")


@_attrs_define
class MemorySummary:
    """
    Attributes:
        confidence (float):
        created_at (None | str):
        id (str):
        importance (float):
        kind (str):
        review_status (MemorySummaryReviewStatus):
        revision (int):
        scope (None | str):
        scope_slug (None | str):
        source_role (MemorySummarySourceRole):
        status (MemorySummaryStatus):
        subject (None | str):
        subject_slug (None | str):
        tags (list[str]):
        text (str):
        updated_at (None | str):
    """

    confidence: float
    created_at: None | str
    id: str
    importance: float
    kind: str
    review_status: MemorySummaryReviewStatus
    revision: int
    scope: None | str
    scope_slug: None | str
    source_role: MemorySummarySourceRole
    status: MemorySummaryStatus
    subject: None | str
    subject_slug: None | str
    tags: list[str]
    text: str
    updated_at: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        confidence = self.confidence

        created_at: None | str
        created_at = self.created_at

        id = self.id

        importance = self.importance

        kind = self.kind

        review_status = self.review_status.value

        revision = self.revision

        scope: None | str
        scope = self.scope

        scope_slug: None | str
        scope_slug = self.scope_slug

        source_role = self.source_role.value

        status = self.status.value

        subject: None | str
        subject = self.subject

        subject_slug: None | str
        subject_slug = self.subject_slug

        tags = self.tags

        text = self.text

        updated_at: None | str
        updated_at = self.updated_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "confidence": confidence,
                "created_at": created_at,
                "id": id,
                "importance": importance,
                "kind": kind,
                "review_status": review_status,
                "revision": revision,
                "scope": scope,
                "scope_slug": scope_slug,
                "source_role": source_role,
                "status": status,
                "subject": subject,
                "subject_slug": subject_slug,
                "tags": tags,
                "text": text,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        confidence = d.pop("confidence")

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        id = d.pop("id")

        importance = d.pop("importance")

        kind = d.pop("kind")

        review_status = MemorySummaryReviewStatus(d.pop("review_status"))

        revision = d.pop("revision")

        def _parse_scope(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        scope = _parse_scope(d.pop("scope"))

        def _parse_scope_slug(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        scope_slug = _parse_scope_slug(d.pop("scope_slug"))

        source_role = MemorySummarySourceRole(d.pop("source_role"))

        status = MemorySummaryStatus(d.pop("status"))

        def _parse_subject(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        subject = _parse_subject(d.pop("subject"))

        def _parse_subject_slug(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        subject_slug = _parse_subject_slug(d.pop("subject_slug"))

        tags = cast(list[str], d.pop("tags"))

        text = d.pop("text")

        def _parse_updated_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        updated_at = _parse_updated_at(d.pop("updated_at"))

        memory_summary = cls(
            confidence=confidence,
            created_at=created_at,
            id=id,
            importance=importance,
            kind=kind,
            review_status=review_status,
            revision=revision,
            scope=scope,
            scope_slug=scope_slug,
            source_role=source_role,
            status=status,
            subject=subject,
            subject_slug=subject_slug,
            tags=tags,
            text=text,
            updated_at=updated_at,
        )

        memory_summary.additional_properties = d
        return memory_summary

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
