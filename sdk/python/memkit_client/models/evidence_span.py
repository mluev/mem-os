from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.evidence_span_evidence_status import EvidenceSpanEvidenceStatus
from ..types import UNSET, Unset

T = TypeVar("T", bound="EvidenceSpan")


@_attrs_define
class EvidenceSpan:
    """
    Attributes:
        created_at (None | str):
        end_char (int):
        excerpt (str):
        message_id (int):
        role (str):
        start_char (int):
        verified (bool):
        evidence_status (EvidenceSpanEvidenceStatus | Unset):
        supported_revisions (list[int] | Unset):
    """

    created_at: None | str
    end_char: int
    excerpt: str
    message_id: int
    role: str
    start_char: int
    verified: bool
    evidence_status: EvidenceSpanEvidenceStatus | Unset = UNSET
    supported_revisions: list[int] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at: None | str
        created_at = self.created_at

        end_char = self.end_char

        excerpt = self.excerpt

        message_id = self.message_id

        role = self.role

        start_char = self.start_char

        verified = self.verified

        evidence_status: str | Unset = UNSET
        if not isinstance(self.evidence_status, Unset):
            evidence_status = self.evidence_status.value

        supported_revisions: list[int] | Unset = UNSET
        if not isinstance(self.supported_revisions, Unset):
            supported_revisions = self.supported_revisions

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "end_char": end_char,
                "excerpt": excerpt,
                "message_id": message_id,
                "role": role,
                "start_char": start_char,
                "verified": verified,
            }
        )
        if evidence_status is not UNSET:
            field_dict["evidence_status"] = evidence_status
        if supported_revisions is not UNSET:
            field_dict["supported_revisions"] = supported_revisions

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        end_char = d.pop("end_char")

        excerpt = d.pop("excerpt")

        message_id = d.pop("message_id")

        role = d.pop("role")

        start_char = d.pop("start_char")

        verified = d.pop("verified")

        _evidence_status = d.pop("evidence_status", UNSET)
        evidence_status: EvidenceSpanEvidenceStatus | Unset
        if isinstance(_evidence_status, Unset):
            evidence_status = UNSET
        else:
            evidence_status = EvidenceSpanEvidenceStatus(_evidence_status)

        supported_revisions = cast(list[int], d.pop("supported_revisions", UNSET))

        evidence_span = cls(
            created_at=created_at,
            end_char=end_char,
            excerpt=excerpt,
            message_id=message_id,
            role=role,
            start_char=start_char,
            verified=verified,
            evidence_status=evidence_status,
            supported_revisions=supported_revisions,
        )

        evidence_span.additional_properties = d
        return evidence_span

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
