from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.search_memory_review_status import SearchMemoryReviewStatus
from ..models.search_memory_source_role import SearchMemorySourceRole
from ..types import UNSET, Unset

if TYPE_CHECKING:
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
        sources (list[SearchEvidence] | Unset):
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
    sources: list[SearchEvidence] | Unset = UNSET
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

        sources: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.sources, Unset):
            sources = []
            for sources_item_data in self.sources:
                sources_item = sources_item_data.to_dict()
                sources.append(sources_item)

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
        if sources is not UNSET:
            field_dict["sources"] = sources

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
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

        _sources = d.pop("sources", UNSET)
        sources: list[SearchEvidence] | Unset = UNSET
        if _sources is not UNSET:
            sources = []
            for sources_item_data in _sources:
                sources_item = SearchEvidence.from_dict(sources_item_data)

                sources.append(sources_item)

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
            sources=sources,
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
