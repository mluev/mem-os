from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="BackupView")


@_attrs_define
class BackupView:
    """
    Attributes:
        bytes_ (int):
        created_at (datetime.datetime):
        id (UUID):
        kind (str):
        path (str):
        protected (bool):
        sha256 (str):
        verified_at (datetime.datetime | None):
    """

    bytes_: int
    created_at: datetime.datetime
    id: UUID
    kind: str
    path: str
    protected: bool
    sha256: str
    verified_at: datetime.datetime | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        bytes_ = self.bytes_

        created_at = self.created_at.isoformat()

        id = str(self.id)

        kind = self.kind

        path = self.path

        protected = self.protected

        sha256 = self.sha256

        verified_at: None | str
        if isinstance(self.verified_at, datetime.datetime):
            verified_at = self.verified_at.isoformat()
        else:
            verified_at = self.verified_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "bytes": bytes_,
                "created_at": created_at,
                "id": id,
                "kind": kind,
                "path": path,
                "protected": protected,
                "sha256": sha256,
                "verified_at": verified_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        bytes_ = d.pop("bytes")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        id = UUID(d.pop("id"))

        kind = d.pop("kind")

        path = d.pop("path")

        protected = d.pop("protected")

        sha256 = d.pop("sha256")

        def _parse_verified_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                verified_at_type_0 = datetime.datetime.fromisoformat(data)

                return verified_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        verified_at = _parse_verified_at(d.pop("verified_at"))

        backup_view = cls(
            bytes_=bytes_,
            created_at=created_at,
            id=id,
            kind=kind,
            path=path,
            protected=protected,
            sha256=sha256,
            verified_at=verified_at,
        )

        backup_view.additional_properties = d
        return backup_view

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
