from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.review_item_kind import ReviewItemKind
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.memory_summary import MemorySummary
    from ..models.review_item_payload import ReviewItemPayload


T = TypeVar("T", bound="ReviewItem")


@_attrs_define
class ReviewItem:
    """
    Attributes:
        actions (list[str]):
        created_at (None | str):
        id (str):
        kind (ReviewItemKind):
        title (str):
        author (None | str | Unset):
        detail (None | str | Unset):
        error_code (None | str | Unset):
        memory (MemorySummary | Unset):
        memory_id (None | str | Unset):
        payload (ReviewItemPayload | Unset):
        previous_text (None | str | Unset):
        subject (None | str | Unset):
    """

    actions: list[str]
    created_at: None | str
    id: str
    kind: ReviewItemKind
    title: str
    author: None | str | Unset = UNSET
    detail: None | str | Unset = UNSET
    error_code: None | str | Unset = UNSET
    memory: MemorySummary | Unset = UNSET
    memory_id: None | str | Unset = UNSET
    payload: ReviewItemPayload | Unset = UNSET
    previous_text: None | str | Unset = UNSET
    subject: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        actions = self.actions

        created_at: None | str
        created_at = self.created_at

        id = self.id

        kind = self.kind.value

        title = self.title

        author: None | str | Unset
        if isinstance(self.author, Unset):
            author = UNSET
        else:
            author = self.author

        detail: None | str | Unset
        if isinstance(self.detail, Unset):
            detail = UNSET
        else:
            detail = self.detail

        error_code: None | str | Unset
        if isinstance(self.error_code, Unset):
            error_code = UNSET
        else:
            error_code = self.error_code

        memory: dict[str, Any] | Unset = UNSET
        if not isinstance(self.memory, Unset):
            memory = self.memory.to_dict()

        memory_id: None | str | Unset
        if isinstance(self.memory_id, Unset):
            memory_id = UNSET
        else:
            memory_id = self.memory_id

        payload: dict[str, Any] | Unset = UNSET
        if not isinstance(self.payload, Unset):
            payload = self.payload.to_dict()

        previous_text: None | str | Unset
        if isinstance(self.previous_text, Unset):
            previous_text = UNSET
        else:
            previous_text = self.previous_text

        subject: None | str | Unset
        if isinstance(self.subject, Unset):
            subject = UNSET
        else:
            subject = self.subject

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "actions": actions,
                "created_at": created_at,
                "id": id,
                "kind": kind,
                "title": title,
            }
        )
        if author is not UNSET:
            field_dict["author"] = author
        if detail is not UNSET:
            field_dict["detail"] = detail
        if error_code is not UNSET:
            field_dict["error_code"] = error_code
        if memory is not UNSET:
            field_dict["memory"] = memory
        if memory_id is not UNSET:
            field_dict["memory_id"] = memory_id
        if payload is not UNSET:
            field_dict["payload"] = payload
        if previous_text is not UNSET:
            field_dict["previous_text"] = previous_text
        if subject is not UNSET:
            field_dict["subject"] = subject

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_summary import MemorySummary
        from ..models.review_item_payload import ReviewItemPayload

        d = dict(src_dict)
        actions = cast(list[str], d.pop("actions"))

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        id = d.pop("id")

        kind = ReviewItemKind(d.pop("kind"))

        title = d.pop("title")

        def _parse_author(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        author = _parse_author(d.pop("author", UNSET))

        def _parse_detail(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        detail = _parse_detail(d.pop("detail", UNSET))

        def _parse_error_code(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error_code = _parse_error_code(d.pop("error_code", UNSET))

        _memory = d.pop("memory", UNSET)
        memory: MemorySummary | Unset
        if isinstance(_memory, Unset):
            memory = UNSET
        else:
            memory = MemorySummary.from_dict(_memory)

        def _parse_memory_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        memory_id = _parse_memory_id(d.pop("memory_id", UNSET))

        _payload = d.pop("payload", UNSET)
        payload: ReviewItemPayload | Unset
        if isinstance(_payload, Unset):
            payload = UNSET
        else:
            payload = ReviewItemPayload.from_dict(_payload)

        def _parse_previous_text(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        previous_text = _parse_previous_text(d.pop("previous_text", UNSET))

        def _parse_subject(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        subject = _parse_subject(d.pop("subject", UNSET))

        review_item = cls(
            actions=actions,
            created_at=created_at,
            id=id,
            kind=kind,
            title=title,
            author=author,
            detail=detail,
            error_code=error_code,
            memory=memory,
            memory_id=memory_id,
            payload=payload,
            previous_text=previous_text,
            subject=subject,
        )

        review_item.additional_properties = d
        return review_item

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
