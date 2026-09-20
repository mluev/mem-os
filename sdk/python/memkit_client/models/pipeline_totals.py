from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="PipelineTotals")


@_attrs_define
class PipelineTotals:
    """
    Attributes:
        acceptance_rate (float | None):
        month_calls (int):
        month_errors (int):
        month_reserved_usd (float):
        month_spend_usd (float):
    """

    acceptance_rate: float | None
    month_calls: int
    month_errors: int
    month_reserved_usd: float
    month_spend_usd: float
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        acceptance_rate: float | None
        acceptance_rate = self.acceptance_rate

        month_calls = self.month_calls

        month_errors = self.month_errors

        month_reserved_usd = self.month_reserved_usd

        month_spend_usd = self.month_spend_usd

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "acceptance_rate": acceptance_rate,
                "month_calls": month_calls,
                "month_errors": month_errors,
                "month_reserved_usd": month_reserved_usd,
                "month_spend_usd": month_spend_usd,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_acceptance_rate(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        acceptance_rate = _parse_acceptance_rate(d.pop("acceptance_rate"))

        month_calls = d.pop("month_calls")

        month_errors = d.pop("month_errors")

        month_reserved_usd = d.pop("month_reserved_usd")

        month_spend_usd = d.pop("month_spend_usd")

        pipeline_totals = cls(
            acceptance_rate=acceptance_rate,
            month_calls=month_calls,
            month_errors=month_errors,
            month_reserved_usd=month_reserved_usd,
            month_spend_usd=month_spend_usd,
        )

        pipeline_totals.additional_properties = d
        return pipeline_totals

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
