from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.memory_patch_context_type_0 import MemoryPatchContextType0


T = TypeVar("T", bound="MemoryPatch")


@_attrs_define
class MemoryPatch:
    """
    Attributes:
        expected_revision (int):
        clear_valid_until (bool | Unset):  Default: False.
        confidence (float | None | Unset):
        context (MemoryPatchContextType0 | None | Unset):
        importance (float | None | Unset):
        kind (None | str | Unset):
        move_context (bool | Unset):  Default: False.
        tags (list[str] | None | Unset):
        text (None | str | Unset):
        valid_until (datetime.datetime | None | Unset):
    """

    expected_revision: int
    clear_valid_until: bool | Unset = False
    confidence: float | None | Unset = UNSET
    context: MemoryPatchContextType0 | None | Unset = UNSET
    importance: float | None | Unset = UNSET
    kind: None | str | Unset = UNSET
    move_context: bool | Unset = False
    tags: list[str] | None | Unset = UNSET
    text: None | str | Unset = UNSET
    valid_until: datetime.datetime | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.memory_patch_context_type_0 import MemoryPatchContextType0

        expected_revision = self.expected_revision

        clear_valid_until = self.clear_valid_until

        confidence: float | None | Unset
        if isinstance(self.confidence, Unset):
            confidence = UNSET
        else:
            confidence = self.confidence

        context: dict[str, Any] | None | Unset
        if isinstance(self.context, Unset):
            context = UNSET
        elif isinstance(self.context, MemoryPatchContextType0):
            context = self.context.to_dict()
        else:
            context = self.context

        importance: float | None | Unset
        if isinstance(self.importance, Unset):
            importance = UNSET
        else:
            importance = self.importance

        kind: None | str | Unset
        if isinstance(self.kind, Unset):
            kind = UNSET
        else:
            kind = self.kind

        move_context = self.move_context

        tags: list[str] | None | Unset
        if isinstance(self.tags, Unset):
            tags = UNSET
        elif isinstance(self.tags, list):
            tags = self.tags

        else:
            tags = self.tags

        text: None | str | Unset
        if isinstance(self.text, Unset):
            text = UNSET
        else:
            text = self.text

        valid_until: None | str | Unset
        if isinstance(self.valid_until, Unset):
            valid_until = UNSET
        elif isinstance(self.valid_until, datetime.datetime):
            valid_until = self.valid_until.isoformat()
        else:
            valid_until = self.valid_until

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "expected_revision": expected_revision,
            }
        )
        if clear_valid_until is not UNSET:
            field_dict["clear_valid_until"] = clear_valid_until
        if confidence is not UNSET:
            field_dict["confidence"] = confidence
        if context is not UNSET:
            field_dict["context"] = context
        if importance is not UNSET:
            field_dict["importance"] = importance
        if kind is not UNSET:
            field_dict["kind"] = kind
        if move_context is not UNSET:
            field_dict["move_context"] = move_context
        if tags is not UNSET:
            field_dict["tags"] = tags
        if text is not UNSET:
            field_dict["text"] = text
        if valid_until is not UNSET:
            field_dict["valid_until"] = valid_until

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_patch_context_type_0 import MemoryPatchContextType0

        d = dict(src_dict)
        expected_revision = d.pop("expected_revision")

        clear_valid_until = d.pop("clear_valid_until", UNSET)

        def _parse_confidence(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        confidence = _parse_confidence(d.pop("confidence", UNSET))

        def _parse_context(data: object) -> MemoryPatchContextType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                context_type_0 = MemoryPatchContextType0.from_dict(data)

                return context_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MemoryPatchContextType0 | None | Unset, data)

        context = _parse_context(d.pop("context", UNSET))

        def _parse_importance(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        importance = _parse_importance(d.pop("importance", UNSET))

        def _parse_kind(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        kind = _parse_kind(d.pop("kind", UNSET))

        move_context = d.pop("move_context", UNSET)

        def _parse_tags(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                tags_type_0 = cast(list[str], data)

                return tags_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        tags = _parse_tags(d.pop("tags", UNSET))

        def _parse_text(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        text = _parse_text(d.pop("text", UNSET))

        def _parse_valid_until(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                valid_until_type_0 = datetime.datetime.fromisoformat(data)

                return valid_until_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        valid_until = _parse_valid_until(d.pop("valid_until", UNSET))

        memory_patch = cls(
            expected_revision=expected_revision,
            clear_valid_until=clear_valid_until,
            confidence=confidence,
            context=context,
            importance=importance,
            kind=kind,
            move_context=move_context,
            tags=tags,
            text=text,
            valid_until=valid_until,
        )

        return memory_patch
