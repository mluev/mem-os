from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.session_view_context import SessionViewContext


T = TypeVar("T", bound="SessionView")


@_attrs_define
class SessionView:
    """
    Attributes:
        agent_id (str):
        context (SessionViewContext):
        ended_at (None | str):
        extracted (int):
        id (str):
        messages (int):
        scope (str):
        scope_slug (str):
        started_at (None | str):
        user (None | str):
    """

    agent_id: str
    context: SessionViewContext
    ended_at: None | str
    extracted: int
    id: str
    messages: int
    scope: str
    scope_slug: str
    started_at: None | str
    user: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent_id = self.agent_id

        context = self.context.to_dict()

        ended_at: None | str
        ended_at = self.ended_at

        extracted = self.extracted

        id = self.id

        messages = self.messages

        scope = self.scope

        scope_slug = self.scope_slug

        started_at: None | str
        started_at = self.started_at

        user: None | str
        user = self.user

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "agent_id": agent_id,
                "context": context,
                "ended_at": ended_at,
                "extracted": extracted,
                "id": id,
                "messages": messages,
                "scope": scope,
                "scope_slug": scope_slug,
                "started_at": started_at,
                "user": user,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.session_view_context import SessionViewContext

        d = dict(src_dict)
        agent_id = d.pop("agent_id")

        context = SessionViewContext.from_dict(d.pop("context"))

        def _parse_ended_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        ended_at = _parse_ended_at(d.pop("ended_at"))

        extracted = d.pop("extracted")

        id = d.pop("id")

        messages = d.pop("messages")

        scope = d.pop("scope")

        scope_slug = d.pop("scope_slug")

        def _parse_started_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        started_at = _parse_started_at(d.pop("started_at"))

        def _parse_user(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        user = _parse_user(d.pop("user"))

        session_view = cls(
            agent_id=agent_id,
            context=context,
            ended_at=ended_at,
            extracted=extracted,
            id=id,
            messages=messages,
            scope=scope,
            scope_slug=scope_slug,
            started_at=started_at,
            user=user,
        )

        session_view.additional_properties = d
        return session_view

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
