from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="StageLatency")


@_attrs_define
class StageLatency:
    """
    Attributes:
        p50 (float | None):
        p95 (float | None):
    """

    p50: float | None
    p95: float | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        p50: float | None
        p50 = self.p50

        p95: float | None
        p95 = self.p95

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "p50": p50,
                "p95": p95,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_p50(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        p50 = _parse_p50(d.pop("p50"))

        def _parse_p95(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        p95 = _parse_p95(d.pop("p95"))

        stage_latency = cls(
            p50=p50,
            p95=p95,
        )

        stage_latency.additional_properties = d
        return stage_latency

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
