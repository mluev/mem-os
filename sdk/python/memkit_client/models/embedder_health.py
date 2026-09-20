from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="EmbedderHealth")


@_attrs_define
class EmbedderHealth:
    """
    Attributes:
        device (None | str):
        ready (bool):
        revision (str):
    """

    device: None | str
    ready: bool
    revision: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        device: None | str
        device = self.device

        ready = self.ready

        revision = self.revision

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "device": device,
                "ready": ready,
                "revision": revision,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_device(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        device = _parse_device(d.pop("device"))

        ready = d.pop("ready")

        revision = d.pop("revision")

        embedder_health = cls(
            device=device,
            ready=ready,
            revision=revision,
        )

        embedder_health.additional_properties = d
        return embedder_health

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
