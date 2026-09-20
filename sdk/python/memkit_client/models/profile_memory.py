from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.profile_memory_review_status import ProfileMemoryReviewStatus
from ..models.profile_memory_source_role import ProfileMemorySourceRole

T = TypeVar("T", bound="ProfileMemory")


@_attrs_define
class ProfileMemory:
    """
    Attributes:
        id (str):
        kind (str):
        review_status (ProfileMemoryReviewStatus):
        scope (None | str):
        source_role (ProfileMemorySourceRole):
        subject (None | str):
        text (str):
        updated_at (None | str):
    """

    id: str
    kind: str
    review_status: ProfileMemoryReviewStatus
    scope: None | str
    source_role: ProfileMemorySourceRole
    subject: None | str
    text: str
    updated_at: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        kind = self.kind

        review_status = self.review_status.value

        scope: None | str
        scope = self.scope

        source_role = self.source_role.value

        subject: None | str
        subject = self.subject

        text = self.text

        updated_at: None | str
        updated_at = self.updated_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "kind": kind,
                "review_status": review_status,
                "scope": scope,
                "source_role": source_role,
                "subject": subject,
                "text": text,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        kind = d.pop("kind")

        review_status = ProfileMemoryReviewStatus(d.pop("review_status"))

        def _parse_scope(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        scope = _parse_scope(d.pop("scope"))

        source_role = ProfileMemorySourceRole(d.pop("source_role"))

        def _parse_subject(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        subject = _parse_subject(d.pop("subject"))

        text = d.pop("text")

        def _parse_updated_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        updated_at = _parse_updated_at(d.pop("updated_at"))

        profile_memory = cls(
            id=id,
            kind=kind,
            review_status=review_status,
            scope=scope,
            source_role=source_role,
            subject=subject,
            text=text,
            updated_at=updated_at,
        )

        profile_memory.additional_properties = d
        return profile_memory

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
