from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.person_usage_role import PersonUsageRole

T = TypeVar("T", bound="PersonUsage")


@_attrs_define
class PersonUsage:
    """
    Attributes:
        disabled (bool):
        display_name (str):
        handle (str):
        key_last_used_at (None | str):
        memories (int):
        memories_all_time (int):
        month_spend_usd (float):
        role (PersonUsageRole):
        searches (int):
        sessions (int):
    """

    disabled: bool
    display_name: str
    handle: str
    key_last_used_at: None | str
    memories: int
    memories_all_time: int
    month_spend_usd: float
    role: PersonUsageRole
    searches: int
    sessions: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        disabled = self.disabled

        display_name = self.display_name

        handle = self.handle

        key_last_used_at: None | str
        key_last_used_at = self.key_last_used_at

        memories = self.memories

        memories_all_time = self.memories_all_time

        month_spend_usd = self.month_spend_usd

        role = self.role.value

        searches = self.searches

        sessions = self.sessions

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "disabled": disabled,
                "display_name": display_name,
                "handle": handle,
                "key_last_used_at": key_last_used_at,
                "memories": memories,
                "memories_all_time": memories_all_time,
                "month_spend_usd": month_spend_usd,
                "role": role,
                "searches": searches,
                "sessions": sessions,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        disabled = d.pop("disabled")

        display_name = d.pop("display_name")

        handle = d.pop("handle")

        def _parse_key_last_used_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        key_last_used_at = _parse_key_last_used_at(d.pop("key_last_used_at"))

        memories = d.pop("memories")

        memories_all_time = d.pop("memories_all_time")

        month_spend_usd = d.pop("month_spend_usd")

        role = PersonUsageRole(d.pop("role"))

        searches = d.pop("searches")

        sessions = d.pop("sessions")

        person_usage = cls(
            disabled=disabled,
            display_name=display_name,
            handle=handle,
            key_last_used_at=key_last_used_at,
            memories=memories,
            memories_all_time=memories_all_time,
            month_spend_usd=month_spend_usd,
            role=role,
            searches=searches,
            sessions=sessions,
        )

        person_usage.additional_properties = d
        return person_usage

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
