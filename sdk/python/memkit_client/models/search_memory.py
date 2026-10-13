from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.search_memory_review_status import SearchMemoryReviewStatus
from ..models.search_memory_source_role import SearchMemorySourceRole
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.linked_memory import LinkedMemory
    from ..models.search_evidence import SearchEvidence
    from ..models.search_memory_context import SearchMemoryContext


T = TypeVar("T", bound="SearchMemory")


@_attrs_define
class SearchMemory:
    """
    Attributes:
        context (SearchMemoryContext):
        entity (float):
        id (str):
        importance (float):
        kind (str):
        lexical (float):
        recency (float):
        review_status (SearchMemoryReviewStatus):
        revision (int):
        scope (None | str):
        scope_slug (None | str):
        score (float):
        similarity (float):
        source_role (SearchMemorySourceRole):
        subject (None | str):
        subject_slug (None | str):
        tags (list[str]):
        text (str):
        updated_at (str):
        document_date (None | str | Unset):
        event_dates (list[str] | Unset):
        history (list[LinkedMemory] | Unset):
        is_static (bool | Unset):
        related (list[LinkedMemory] | Unset):
        source_count (int | Unset):
        sources (list[SearchEvidence] | Unset):
        temporal (float | Unset):
    """

    context: SearchMemoryContext
    entity: float
    id: str
    importance: float
    kind: str
    lexical: float
    recency: float
    review_status: SearchMemoryReviewStatus
    revision: int
    scope: None | str
    scope_slug: None | str
    score: float
    similarity: float
    source_role: SearchMemorySourceRole
    subject: None | str
    subject_slug: None | str
    tags: list[str]
    text: str
    updated_at: str
    document_date: None | str | Unset = UNSET
    event_dates: list[str] | Unset = UNSET
    history: list[LinkedMemory] | Unset = UNSET
    is_static: bool | Unset = UNSET
    related: list[LinkedMemory] | Unset = UNSET
    source_count: int | Unset = UNSET
    sources: list[SearchEvidence] | Unset = UNSET
    temporal: float | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        context = self.context.to_dict()

        entity = self.entity

        id = self.id

        importance = self.importance

        kind = self.kind

        lexical = self.lexical

        recency = self.recency

        review_status = self.review_status.value

        revision = self.revision

        scope: None | str
        scope = self.scope

        scope_slug: None | str
        scope_slug = self.scope_slug

        score = self.score

        similarity = self.similarity

        source_role = self.source_role.value

        subject: None | str
        subject = self.subject

        subject_slug: None | str
        subject_slug = self.subject_slug

        tags = self.tags

        text = self.text

        updated_at = self.updated_at

        document_date: None | str | Unset
        if isinstance(self.document_date, Unset):
            document_date = UNSET
        else:
            document_date = self.document_date

        event_dates: list[str] | Unset = UNSET
        if not isinstance(self.event_dates, Unset):
            event_dates = self.event_dates

        history: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.history, Unset):
            history = []
            for history_item_data in self.history:
                history_item = history_item_data.to_dict()
                history.append(history_item)

        is_static = self.is_static

        related: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.related, Unset):
            related = []
            for related_item_data in self.related:
                related_item = related_item_data.to_dict()
                related.append(related_item)

        source_count = self.source_count

        sources: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.sources, Unset):
            sources = []
            for sources_item_data in self.sources:
                sources_item = sources_item_data.to_dict()
                sources.append(sources_item)

        temporal = self.temporal

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "context": context,
                "entity": entity,
                "id": id,
                "importance": importance,
                "kind": kind,
                "lexical": lexical,
                "recency": recency,
                "review_status": review_status,
                "revision": revision,
                "scope": scope,
                "scope_slug": scope_slug,
                "score": score,
                "similarity": similarity,
                "source_role": source_role,
                "subject": subject,
                "subject_slug": subject_slug,
                "tags": tags,
                "text": text,
                "updated_at": updated_at,
            }
        )
        if document_date is not UNSET:
            field_dict["document_date"] = document_date
        if event_dates is not UNSET:
            field_dict["event_dates"] = event_dates
        if history is not UNSET:
            field_dict["history"] = history
        if is_static is not UNSET:
            field_dict["is_static"] = is_static
        if related is not UNSET:
            field_dict["related"] = related
        if source_count is not UNSET:
            field_dict["source_count"] = source_count
        if sources is not UNSET:
            field_dict["sources"] = sources
        if temporal is not UNSET:
            field_dict["temporal"] = temporal

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.linked_memory import LinkedMemory
        from ..models.search_evidence import SearchEvidence
        from ..models.search_memory_context import SearchMemoryContext

        d = dict(src_dict)
        context = SearchMemoryContext.from_dict(d.pop("context"))

        entity = d.pop("entity")

        id = d.pop("id")

        importance = d.pop("importance")

        kind = d.pop("kind")

        lexical = d.pop("lexical")

        recency = d.pop("recency")

        review_status = SearchMemoryReviewStatus(d.pop("review_status"))

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

        score = d.pop("score")

        similarity = d.pop("similarity")

        source_role = SearchMemorySourceRole(d.pop("source_role"))

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

        updated_at = d.pop("updated_at")

        def _parse_document_date(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        document_date = _parse_document_date(d.pop("document_date", UNSET))

        event_dates = cast(list[str], d.pop("event_dates", UNSET))

        _history = d.pop("history", UNSET)
        history: list[LinkedMemory] | Unset = UNSET
        if _history is not UNSET:
            history = []
            for history_item_data in _history:
                history_item = LinkedMemory.from_dict(history_item_data)

                history.append(history_item)

        is_static = d.pop("is_static", UNSET)

        _related = d.pop("related", UNSET)
        related: list[LinkedMemory] | Unset = UNSET
        if _related is not UNSET:
            related = []
            for related_item_data in _related:
                related_item = LinkedMemory.from_dict(related_item_data)

                related.append(related_item)

        source_count = d.pop("source_count", UNSET)

        _sources = d.pop("sources", UNSET)
        sources: list[SearchEvidence] | Unset = UNSET
        if _sources is not UNSET:
            sources = []
            for sources_item_data in _sources:
                sources_item = SearchEvidence.from_dict(sources_item_data)

                sources.append(sources_item)

        temporal = d.pop("temporal", UNSET)

        search_memory = cls(
            context=context,
            entity=entity,
            id=id,
            importance=importance,
            kind=kind,
            lexical=lexical,
            recency=recency,
            review_status=review_status,
            revision=revision,
            scope=scope,
            scope_slug=scope_slug,
            score=score,
            similarity=similarity,
            source_role=source_role,
            subject=subject,
            subject_slug=subject_slug,
            tags=tags,
            text=text,
            updated_at=updated_at,
            document_date=document_date,
            event_dates=event_dates,
            history=history,
            is_static=is_static,
            related=related,
            source_count=source_count,
            sources=sources,
            temporal=temporal,
        )

        search_memory.additional_properties = d
        return search_memory

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
