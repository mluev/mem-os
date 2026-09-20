from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="RetrievalTotals")


@_attrs_define
class RetrievalTotals:
    """
    Attributes:
        abstention_rate (float | None):
        p50_ms (float | None):
        p95_ms (float | None):
        searches (int):
    """

    abstention_rate: float | None
    p50_ms: float | None
    p95_ms: float | None
    searches: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        abstention_rate: float | None
        abstention_rate = self.abstention_rate

        p50_ms: float | None
        p50_ms = self.p50_ms

        p95_ms: float | None
        p95_ms = self.p95_ms

        searches = self.searches

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "abstention_rate": abstention_rate,
                "p50_ms": p50_ms,
                "p95_ms": p95_ms,
                "searches": searches,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_abstention_rate(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        abstention_rate = _parse_abstention_rate(d.pop("abstention_rate"))

        def _parse_p50_ms(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        p50_ms = _parse_p50_ms(d.pop("p50_ms"))

        def _parse_p95_ms(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        p95_ms = _parse_p95_ms(d.pop("p95_ms"))

        searches = d.pop("searches")

        retrieval_totals = cls(
            abstention_rate=abstention_rate,
            p50_ms=p50_ms,
            p95_ms=p95_ms,
            searches=searches,
        )

        retrieval_totals.additional_properties = d
        return retrieval_totals

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
