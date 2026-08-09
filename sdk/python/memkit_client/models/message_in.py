from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.message_in_role import MessageInRole
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.message_in_context import MessageInContext


T = TypeVar("T", bound="MessageIn")


@_attrs_define
class MessageIn:
    """
    Attributes:
        content (str):
        role (MessageInRole):
        session_id (str):
        agent_id (str | Unset):  Default: 'chat'.
        context (MessageInContext | Unset):
        created_at (datetime.datetime | None | Unset):
        external_id (None | str | Unset):
        external_source (None | str | Unset):
    """

    content: str
    role: MessageInRole
    session_id: str
    agent_id: str | Unset = "chat"
    context: MessageInContext | Unset = UNSET
    created_at: datetime.datetime | None | Unset = UNSET
    external_id: None | str | Unset = UNSET
    external_source: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        content = self.content

        role = self.role.value

        session_id = self.session_id

        agent_id = self.agent_id

        context: dict[str, Any] | Unset = UNSET
        if not isinstance(self.context, Unset):
            context = self.context.to_dict()

        created_at: None | str | Unset
        if isinstance(self.created_at, Unset):
            created_at = UNSET
        elif isinstance(self.created_at, datetime.datetime):
            created_at = self.created_at.isoformat()
        else:
            created_at = self.created_at

        external_id: None | str | Unset
        if isinstance(self.external_id, Unset):
            external_id = UNSET
        else:
            external_id = self.external_id

        external_source: None | str | Unset
        if isinstance(self.external_source, Unset):
            external_source = UNSET
        else:
            external_source = self.external_source

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "content": content,
                "role": role,
                "session_id": session_id,
            }
        )
        if agent_id is not UNSET:
            field_dict["agent_id"] = agent_id
        if context is not UNSET:
            field_dict["context"] = context
        if created_at is not UNSET:
            field_dict["created_at"] = created_at
        if external_id is not UNSET:
            field_dict["external_id"] = external_id
        if external_source is not UNSET:
            field_dict["external_source"] = external_source

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.message_in_context import MessageInContext

        d = dict(src_dict)
        content = d.pop("content")

        role = MessageInRole(d.pop("role"))

        session_id = d.pop("session_id")

        agent_id = d.pop("agent_id", UNSET)

        _context = d.pop("context", UNSET)
        context: MessageInContext | Unset
        if isinstance(_context, Unset):
            context = UNSET
        else:
            context = MessageInContext.from_dict(_context)

        def _parse_created_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                created_at_type_0 = datetime.datetime.fromisoformat(data)

                return created_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        created_at = _parse_created_at(d.pop("created_at", UNSET))

        def _parse_external_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        external_id = _parse_external_id(d.pop("external_id", UNSET))

        def _parse_external_source(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        external_source = _parse_external_source(d.pop("external_source", UNSET))

        message_in = cls(
            content=content,
            role=role,
            session_id=session_id,
            agent_id=agent_id,
            context=context,
            created_at=created_at,
            external_id=external_id,
            external_source=external_source,
        )

        return message_in
