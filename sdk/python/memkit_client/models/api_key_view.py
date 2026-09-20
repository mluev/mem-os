from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="ApiKeyView")


@_attrs_define
class ApiKeyView:
    """
    Attributes:
        created_at (None | str):
        id (str):
        key_prefix (str):
        last_used_at (None | str):
        name (str):
        revoked_at (None | str):
    """

    created_at: None | str
    id: str
    key_prefix: str
    last_used_at: None | str
    name: str
    revoked_at: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at: None | str
        created_at = self.created_at

        id = self.id

        key_prefix = self.key_prefix

        last_used_at: None | str
        last_used_at = self.last_used_at

        name = self.name

        revoked_at: None | str
        revoked_at = self.revoked_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "id": id,
                "key_prefix": key_prefix,
                "last_used_at": last_used_at,
                "name": name,
                "revoked_at": revoked_at,
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

        id = d.pop("id")

        key_prefix = d.pop("key_prefix")

        def _parse_last_used_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        last_used_at = _parse_last_used_at(d.pop("last_used_at"))

        name = d.pop("name")

        def _parse_revoked_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        revoked_at = _parse_revoked_at(d.pop("revoked_at"))

        api_key_view = cls(
            created_at=created_at,
            id=id,
            key_prefix=key_prefix,
            last_used_at=last_used_at,
            name=name,
            revoked_at=revoked_at,
        )

        api_key_view.additional_properties = d
        return api_key_view

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
