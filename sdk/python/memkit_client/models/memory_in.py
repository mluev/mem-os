from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.memory_in_source_role import MemoryInSourceRole
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.memory_in_context import MemoryInContext


T = TypeVar("T", bound="MemoryIn")


@_attrs_define
class MemoryIn:
    """
    Attributes:
        kind (str):
        source_role (MemoryInSourceRole):
        text (str):
        agent_id (None | str | Unset):
        confidence (float | Unset):  Default: 0.9.
        context (MemoryInContext | Unset):
        importance (float | Unset):  Default: 0.6.
        tags (list[str] | Unset):
        valid_until (datetime.datetime | None | Unset):
    """

    kind: str
    source_role: MemoryInSourceRole
    text: str
    agent_id: None | str | Unset = UNSET
    confidence: float | Unset = 0.9
    context: MemoryInContext | Unset = UNSET
    importance: float | Unset = 0.6
    tags: list[str] | Unset = UNSET
    valid_until: datetime.datetime | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        source_role = self.source_role.value

        text = self.text

        agent_id: None | str | Unset
        if isinstance(self.agent_id, Unset):
            agent_id = UNSET
        else:
            agent_id = self.agent_id

        confidence = self.confidence

        context: dict[str, Any] | Unset = UNSET
        if not isinstance(self.context, Unset):
            context = self.context.to_dict()

        importance = self.importance

        tags: list[str] | Unset = UNSET
        if not isinstance(self.tags, Unset):
            tags = self.tags

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
                "kind": kind,
                "source_role": source_role,
                "text": text,
            }
        )
        if agent_id is not UNSET:
            field_dict["agent_id"] = agent_id
        if confidence is not UNSET:
            field_dict["confidence"] = confidence
        if context is not UNSET:
            field_dict["context"] = context
        if importance is not UNSET:
            field_dict["importance"] = importance
        if tags is not UNSET:
            field_dict["tags"] = tags
        if valid_until is not UNSET:
            field_dict["valid_until"] = valid_until

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_in_context import MemoryInContext

        d = dict(src_dict)
        kind = d.pop("kind")

        source_role = MemoryInSourceRole(d.pop("source_role"))

        text = d.pop("text")

        def _parse_agent_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        agent_id = _parse_agent_id(d.pop("agent_id", UNSET))

        confidence = d.pop("confidence", UNSET)

        _context = d.pop("context", UNSET)
        context: MemoryInContext | Unset
        if isinstance(_context, Unset):
            context = UNSET
        else:
            context = MemoryInContext.from_dict(_context)

        importance = d.pop("importance", UNSET)

        tags = cast(list[str], d.pop("tags", UNSET))

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

        memory_in = cls(
            kind=kind,
            source_role=source_role,
            text=text,
            agent_id=agent_id,
            confidence=confidence,
            context=context,
            importance=importance,
            tags=tags,
            valid_until=valid_until,
        )

        return memory_in
