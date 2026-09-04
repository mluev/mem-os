from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="KeyCreatedOut")


@_attrs_define
class KeyCreatedOut:
    """
    Attributes:
        id (str):
        key_prefix (str):
        name (str):
        secret (str):
    """

    id: str
    key_prefix: str
    name: str
    secret: str

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        key_prefix = self.key_prefix

        name = self.name

        secret = self.secret

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "key_prefix": key_prefix,
                "name": name,
                "secret": secret,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        key_prefix = d.pop("key_prefix")

        name = d.pop("name")

        secret = d.pop("secret")

        key_created_out = cls(
            id=id,
            key_prefix=key_prefix,
            name=name,
            secret=secret,
        )

        return key_created_out
