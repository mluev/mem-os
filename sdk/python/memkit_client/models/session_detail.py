from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="SessionDetail")


@_attrs_define
class SessionDetail:
    """
    Attributes:
        agent_id (str):
        ended_at (None | str):
        id (str):
        scope_id (str):
        started_at (None | str):
        user_id (str):
    """

    agent_id: str
    ended_at: None | str
    id: str
    scope_id: str
    started_at: None | str
    user_id: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent_id = self.agent_id

        ended_at: None | str
        ended_at = self.ended_at

        id = self.id

        scope_id = self.scope_id

        started_at: None | str
        started_at = self.started_at

        user_id = self.user_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "agent_id": agent_id,
                "ended_at": ended_at,
                "id": id,
                "scope_id": scope_id,
                "started_at": started_at,
                "user_id": user_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent_id = d.pop("agent_id")

        def _parse_ended_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        ended_at = _parse_ended_at(d.pop("ended_at"))

        id = d.pop("id")

        scope_id = d.pop("scope_id")

        def _parse_started_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        started_at = _parse_started_at(d.pop("started_at"))

        user_id = d.pop("user_id")

        session_detail = cls(
            agent_id=agent_id,
            ended_at=ended_at,
            id=id,
            scope_id=scope_id,
            started_at=started_at,
            user_id=user_id,
        )

        session_detail.additional_properties = d
        return session_detail

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
