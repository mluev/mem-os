from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.search_evidence_evidence_status import SearchEvidenceEvidenceStatus

T = TypeVar("T", bound="SearchEvidence")


@_attrs_define
class SearchEvidence:
    """
    Attributes:
        created_at (None | str):
        evidence_status (SearchEvidenceEvidenceStatus):
        excerpt (str):
        message_id (int):
        revision (int | None):
        role (str):
    """

    created_at: None | str
    evidence_status: SearchEvidenceEvidenceStatus
    excerpt: str
    message_id: int
    revision: int | None
    role: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at: None | str
        created_at = self.created_at

        evidence_status = self.evidence_status.value

        excerpt = self.excerpt

        message_id = self.message_id

        revision: int | None
        revision = self.revision

        role = self.role

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "evidence_status": evidence_status,
                "excerpt": excerpt,
                "message_id": message_id,
                "revision": revision,
                "role": role,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        evidence_status = SearchEvidenceEvidenceStatus(d.pop("evidence_status"))

        excerpt = d.pop("excerpt")

        message_id = d.pop("message_id")

        def _parse_revision(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        revision = _parse_revision(d.pop("revision"))

        role = d.pop("role")

        search_evidence = cls(
            created_at=created_at,
            evidence_status=evidence_status,
            excerpt=excerpt,
            message_id=message_id,
            revision=revision,
            role=role,
        )

        search_evidence.additional_properties = d
        return search_evidence

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
