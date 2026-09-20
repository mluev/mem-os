from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.memory_record_review_status import MemoryRecordReviewStatus
from ..models.memory_record_source_role import MemoryRecordSourceRole
from ..models.memory_record_status import MemoryRecordStatus
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.memory_record_context import MemoryRecordContext


T = TypeVar("T", bound="MemoryRecord")


@_attrs_define
class MemoryRecord:
    """
    Attributes:
        author (None | str):
        confidence (float):
        context (MemoryRecordContext):
        created_at (None | str):
        id (str):
        importance (float):
        kind (str):
        review_status (MemoryRecordReviewStatus):
        revision (int):
        scope (None | str):
        scope_slug (None | str):
        source_role (MemoryRecordSourceRole):
        status (MemoryRecordStatus):
        subject (None | str):
        subject_slug (None | str):
        tags (list[str]):
        text (str):
        updated_at (None | str):
        valid_until (None | str):
        extraction_version (str | Unset):
        judge_run_id (int | None | Unset):
        last_retrieved_at (None | str | Unset):
        retrieval_count (int | Unset):
        sessions (list[str] | Unset):
        writable (bool | Unset):
    """

    author: None | str
    confidence: float
    context: MemoryRecordContext
    created_at: None | str
    id: str
    importance: float
    kind: str
    review_status: MemoryRecordReviewStatus
    revision: int
    scope: None | str
    scope_slug: None | str
    source_role: MemoryRecordSourceRole
    status: MemoryRecordStatus
    subject: None | str
    subject_slug: None | str
    tags: list[str]
    text: str
    updated_at: None | str
    valid_until: None | str
    extraction_version: str | Unset = UNSET
    judge_run_id: int | None | Unset = UNSET
    last_retrieved_at: None | str | Unset = UNSET
    retrieval_count: int | Unset = UNSET
    sessions: list[str] | Unset = UNSET
    writable: bool | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        author: None | str
        author = self.author

        confidence = self.confidence

        context = self.context.to_dict()

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

        valid_until: None | str
        valid_until = self.valid_until

        extraction_version = self.extraction_version

        judge_run_id: int | None | Unset
        if isinstance(self.judge_run_id, Unset):
            judge_run_id = UNSET
        else:
            judge_run_id = self.judge_run_id

        last_retrieved_at: None | str | Unset
        if isinstance(self.last_retrieved_at, Unset):
            last_retrieved_at = UNSET
        else:
            last_retrieved_at = self.last_retrieved_at

        retrieval_count = self.retrieval_count

        sessions: list[str] | Unset = UNSET
        if not isinstance(self.sessions, Unset):
            sessions = self.sessions

        writable = self.writable

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "author": author,
                "confidence": confidence,
                "context": context,
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
                "valid_until": valid_until,
            }
        )
        if extraction_version is not UNSET:
            field_dict["extraction_version"] = extraction_version
        if judge_run_id is not UNSET:
            field_dict["judge_run_id"] = judge_run_id
        if last_retrieved_at is not UNSET:
            field_dict["last_retrieved_at"] = last_retrieved_at
        if retrieval_count is not UNSET:
            field_dict["retrieval_count"] = retrieval_count
        if sessions is not UNSET:
            field_dict["sessions"] = sessions
        if writable is not UNSET:
            field_dict["writable"] = writable

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_record_context import MemoryRecordContext

        d = dict(src_dict)

        def _parse_author(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        author = _parse_author(d.pop("author"))

        confidence = d.pop("confidence")

        context = MemoryRecordContext.from_dict(d.pop("context"))

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        id = d.pop("id")

        importance = d.pop("importance")

        kind = d.pop("kind")

        review_status = MemoryRecordReviewStatus(d.pop("review_status"))

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

        source_role = MemoryRecordSourceRole(d.pop("source_role"))

        status = MemoryRecordStatus(d.pop("status"))

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

        def _parse_valid_until(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        valid_until = _parse_valid_until(d.pop("valid_until"))

        extraction_version = d.pop("extraction_version", UNSET)

        def _parse_judge_run_id(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        judge_run_id = _parse_judge_run_id(d.pop("judge_run_id", UNSET))

        def _parse_last_retrieved_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        last_retrieved_at = _parse_last_retrieved_at(d.pop("last_retrieved_at", UNSET))

        retrieval_count = d.pop("retrieval_count", UNSET)

        sessions = cast(list[str], d.pop("sessions", UNSET))

        writable = d.pop("writable", UNSET)

        memory_record = cls(
            author=author,
            confidence=confidence,
            context=context,
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
            valid_until=valid_until,
            extraction_version=extraction_version,
            judge_run_id=judge_run_id,
            last_retrieved_at=last_retrieved_at,
            retrieval_count=retrieval_count,
            sessions=sessions,
            writable=writable,
        )

        memory_record.additional_properties = d
        return memory_record

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
