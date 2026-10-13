from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.profile_memory_review_status import ProfileMemoryReviewStatus
from ..models.profile_memory_source_role import ProfileMemorySourceRole
from ..types import UNSET, Unset

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
        document_date (None | str | Unset):
        event_dates (list[str] | Unset):
        is_static (bool | Unset):
    """

    id: str
    kind: str
    review_status: ProfileMemoryReviewStatus
    scope: None | str
    source_role: ProfileMemorySourceRole
    subject: None | str
    text: str
    updated_at: None | str
    document_date: None | str | Unset = UNSET
    event_dates: list[str] | Unset = UNSET
    is_static: bool | Unset = UNSET
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

        document_date: None | str | Unset
        if isinstance(self.document_date, Unset):
            document_date = UNSET
        else:
            document_date = self.document_date

        event_dates: list[str] | Unset = UNSET
        if not isinstance(self.event_dates, Unset):
            event_dates = self.event_dates

        is_static = self.is_static

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
        if document_date is not UNSET:
            field_dict["document_date"] = document_date
        if event_dates is not UNSET:
            field_dict["event_dates"] = event_dates
        if is_static is not UNSET:
            field_dict["is_static"] = is_static

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

        def _parse_document_date(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        document_date = _parse_document_date(d.pop("document_date", UNSET))

        event_dates = cast(list[str], d.pop("event_dates", UNSET))

        is_static = d.pop("is_static", UNSET)

        profile_memory = cls(
            id=id,
            kind=kind,
            review_status=review_status,
            scope=scope,
            source_role=source_role,
            subject=subject,
            text=text,
            updated_at=updated_at,
            document_date=document_date,
            event_dates=event_dates,
            is_static=is_static,
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
