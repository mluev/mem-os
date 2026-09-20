from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.message_view_role import MessageViewRole

T = TypeVar("T", bound="MessageView")


@_attrs_define
class MessageView:
    """
    Attributes:
        content (str):
        created_at (None | str):
        id (int):
        processed (bool):
        redacted (bool):
        role (MessageViewRole):
    """

    content: str
    created_at: None | str
    id: int
    processed: bool
    redacted: bool
    role: MessageViewRole
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        content = self.content

        created_at: None | str
        created_at = self.created_at

        id = self.id

        processed = self.processed

        redacted = self.redacted

        role = self.role.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "content": content,
                "created_at": created_at,
                "id": id,
                "processed": processed,
                "redacted": redacted,
                "role": role,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        content = d.pop("content")

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        id = d.pop("id")

        processed = d.pop("processed")

        redacted = d.pop("redacted")

        role = MessageViewRole(d.pop("role"))

        message_view = cls(
            content=content,
            created_at=created_at,
            id=id,
            processed=processed,
            redacted=redacted,
            role=role,
        )

        message_view.additional_properties = d
        return message_view

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
